"""Telegram digest: new flats, price drops and source warnings, in the page's PT-PT voice.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Without them, nothing is sent.
A Telegram failure is logged and never fails the scrape.
"""

from __future__ import annotations

import html
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from scraper.models import Lead, Listing
from scraper.pipeline import RunOutcome
from scraper.store import SourceRun, Store

log = logging.getLogger(__name__)

MAX_PHOTO_MESSAGES = 10
NUDGE_DAYS = (2, 5)  # remind about unanswered contacts on these days, not every day
VISIT_WINDOW = timedelta(hours=36)
MADRID = ZoneInfo("Europe/Madrid")
FAILURE_STREAK = 2
SOURCE_LABELS = {
    "pisos": "pisos.com",
    "enalquiler": "enalquiler",
    "fotocasa": "Fotocasa",
    "idealista": "Idealista",
    "yaencontre": "yaencontre",
    "milanuncios": "Milanuncios",
}
FEATURE_LABELS = {
    "elevator": "elevador",
    "ac": "ar cond.",
    "terrace": "terraço",
    "parking": "garagem",
    "furnished": "mobilado",
    "pets": "aceita animais",
    "pool": "piscina",
}


def _e(text: str | None) -> str:
    return html.escape(text or "", quote=False)


def euros(value: int) -> str:
    return f"{value} €"


def facts(listing: Listing) -> str:
    parts = [euros(listing.price_eur)]
    if listing.bedrooms is not None:
        parts.append(f"{listing.bedrooms} {'quarto' if listing.bedrooms == 1 else 'quartos'}")
    if listing.area_m2 is not None:
        parts.append(f"{listing.area_m2} m²")
    return " · ".join(parts)


def catch_line(listing: Listing) -> str:
    if not listing.features_known:
        return "confirmar extras"
    missing = []
    if listing.property_type != "house" and "elevator" not in listing.features:
        missing.append("sem elevador")
    if "ac" not in listing.features:
        missing.append("sem ar condicionado")
    return " · ".join(missing)


def place(listing: Listing) -> str:
    town, hood = listing.municipality or "", (listing.neighbourhood or "").strip()
    return f"{hood}, {town}" if hood and town and hood != town else hood or town


def caption(listing: Listing) -> str:
    """One new flat, as you'd text it: price first, then the catch, then where."""
    lines = [f"<b>{_e(facts(listing))}</b>"]
    catch = catch_line(listing)
    if catch:
        lines.append(_e(catch))
    lines.append(_e(place(listing)))
    chips = [FEATURE_LABELS[f] for f in FEATURE_LABELS if f in listing.features]
    if chips:
        lines.append(_e(" · ".join(chips)))
    source = SOURCE_LABELS.get(listing.source, listing.source)
    lines.append(f'<a href="{_e(listing.url)}">Abrir anúncio</a> ({_e(source)})')
    return "\n".join(lines)


def truly_new(listings: Sequence[Listing]) -> list[Listing]:
    """Only flats that started their own group; repeats on other portals stay quiet."""
    seen: set[str] = set()
    out = []
    for item in listings:
        if item.group_id not in (None, item.id) or item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out


def failing_sources(store: Store, outcomes: Sequence[RunOutcome]) -> list[SourceRun]:
    """Sources whose last FAILURE_STREAK runs all failed (warn once, on the run that hits it)."""
    failing = []
    for outcome in outcomes:
        if outcome.run.status == "ok":
            continue
        recent = store.recent_runs(outcome.run.source, FAILURE_STREAK + 1)
        streak = 0
        for run in recent:
            if run.status == "ok":
                break
            streak += 1
        if streak == FAILURE_STREAK:
            failing.append(outcome.run)
    return failing


def when_text(at: datetime, now: datetime) -> str:
    """'hoje 18:00' / 'amanhã 18:00' / '28/11 18:00', in Madrid time."""
    local, today = at.astimezone(MADRID), now.astimezone(MADRID).date()
    time = local.strftime("%H:%M")
    if local.date() == today:
        return f"hoje {time}"
    if local.date() == today + timedelta(days=1):
        return f"amanhã {time}"
    return f"{local:%d/%m} {time}"


def build_nudges(pairs: Sequence[tuple[Lead, Listing]], now: datetime) -> list[str]:
    """Unanswered contacts (on day 2 and 5) and visits in the next 36 hours."""
    lines = []
    for lead, listing in pairs:
        label = f"{_e(place(listing)) or 'anúncio'} · {euros(listing.price_eur)}"
        where = f'<a href="{_e(listing.url)}">{label}</a>'
        if lead.stage == "contactado":
            days = (now - lead.stage_at).days
            if days in NUDGE_DAYS:
                lines.append(f"⏳ Sem resposta há {days} dias: {where}. Insistir?")
        elif (
            lead.stage == "visita"
            and lead.next_action_at
            and now <= lead.next_action_at <= now + VISIT_WINDOW
        ):
            lines.append(f"📅 Visita {when_text(lead.next_action_at, now)}: {where}")
    return lines


@dataclass
class Digest:
    new: list[Listing] = field(default_factory=list)
    drops: list[tuple[Listing, int]] = field(default_factory=list)  # (listing, old price)
    warnings: list[SourceRun] = field(default_factory=list)
    nudges: list[str] = field(default_factory=list)
    page_url: str | None = None

    def is_empty(self) -> bool:
        return not (self.new or self.drops or self.warnings or self.nudges)

    def summary(self) -> str | None:
        lines: list[str] = []
        if self.nudges:
            lines.append("<b>Para tratar:</b>")
            lines.extend(self.nudges)
        extra = len(self.new) - MAX_PHOTO_MESSAGES
        if self.new:
            n = len(self.new)
            lines.append(f"<b>{n} {'novo' if n == 1 else 'novos'} hoje.</b>")
            if extra > 0:
                lines.append(f"+{extra} mais na página.")
        if self.drops:
            lines.append("<b>Baixaram de preço:</b>")
            for listing, old in self.drops:
                lines.append(
                    f'• <a href="{_e(listing.url)}">{_e(place(listing)) or "anúncio"}</a>: '
                    f"{euros(old)} → {euros(listing.price_eur)}"
                )
        for run in self.warnings:
            name = SOURCE_LABELS.get(run.source, run.source)
            why = "bloqueado" if run.status == "blocked" else "erro"
            hint = " Vê se o PC está ligado." if run.source == "fotocasa" else ""
            lines.append(f"⚠️ {_e(name)} falhou {FAILURE_STREAK} vezes seguidas ({why}).{hint}")
        if not lines:
            return None
        if self.page_url:
            lines.append(f'<a href="{_e(self.page_url)}">Ver na página</a>')
        return "\n".join(lines)


def build_digest(
    outcomes: Sequence[RunOutcome],
    store: Store,
    page_url: str | None = None,
    nudges: Sequence[str] = (),
) -> Digest:
    new = truly_new([item for o in outcomes for item in o.new_matches])
    drops = []
    for o in outcomes:
        for item in o.price_drops:
            if len(item.price_history) >= 2:
                drops.append((item, item.price_history[-2].price_eur))
    return Digest(
        new=new,
        drops=drops,
        warnings=failing_sources(store, outcomes),
        nudges=list(nudges),
        page_url=page_url,
    )


class Telegram:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        # Telegram downloads each photo from the portal itself, which can take a while.
        self.client = client or httpx.Client(timeout=60)

    @classmethod
    def from_env(cls) -> Telegram | None:
        # Strip: a secret pasted with a trailing newline would otherwise break the URL/chat id.
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        return cls(token, chat) if token and chat else None

    def _post(self, method: str, payload: dict[str, object]) -> None:
        resp = self.client.post(f"{self.base}/{method}", json={"chat_id": self.chat_id, **payload})
        if resp.is_error:
            raise TelegramError(method, resp)

    def _text(self, text: str) -> None:
        self._post(
            "sendMessage", {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        )

    def send(self, digest: Digest) -> int:
        """Send the digest; returns how many messages went out.

        The summary must go through (a failure there means the bot/chat is broken, so stop).
        Each flat is best effort: a photo Telegram can't fetch falls back to text.
        """
        sent = 0
        summary = digest.summary()
        if summary:
            self._text(summary)
            sent += 1
        for listing in digest.new[:MAX_PHOTO_MESSAGES]:
            text = caption(listing)
            try:
                if listing.photos:
                    try:
                        self._post(
                            "sendPhoto",
                            {"photo": listing.photos[0], "caption": text, "parse_mode": "HTML"},
                        )
                    except TelegramError as exc:
                        log.warning("photo not sent, sending text instead: %s", exc)
                        self._text(text)
                else:
                    self._text(text)
                sent += 1
            except (TelegramError, httpx.HTTPError) as exc:
                log.warning("Telegram message skipped: %s", _describe(exc))
        return sent


class TelegramError(Exception):
    """Telegram said no. Carries its status and reason, never the URL (it holds the token)."""

    def __init__(self, method: str, resp: httpx.Response) -> None:
        try:
            reason = str(resp.json().get("description", ""))
        except ValueError:
            reason = ""
        super().__init__(f"{method} {resp.status_code} {reason}".strip())


def _describe(exc: Exception) -> str:
    return str(exc) if isinstance(exc, TelegramError) else type(exc).__name__


def notify(
    outcomes: Sequence[RunOutcome],
    store: Store,
    telegram: Telegram | None,
    include_nudges: bool = False,
    now: datetime | None = None,
) -> int:
    if telegram is None:
        log.info("Telegram not configured; skipping digest")
        return 0
    nudges: list[str] = []
    if include_nudges:  # once a day, from the cloud run only, so they don't arrive twice
        moment = now or datetime.now(MADRID)
        nudges = build_nudges(store.leads_with_listings(["contactado", "visita"]), moment)
    digest = build_digest(outcomes, store, os.environ.get("PAGE_URL"), nudges)
    if digest.is_empty():
        return 0
    try:
        return telegram.send(digest)
    except (TelegramError, httpx.HTTPError) as exc:
        # Never leak the bot token (it's in the URL) into logs.
        log.warning("Telegram send failed: %s", _describe(exc))
        return 0
