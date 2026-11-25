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

import httpx

from scraper.models import Listing
from scraper.pipeline import RunOutcome
from scraper.store import SourceRun, Store

log = logging.getLogger(__name__)

MAX_PHOTO_MESSAGES = 10
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


@dataclass
class Digest:
    new: list[Listing] = field(default_factory=list)
    drops: list[tuple[Listing, int]] = field(default_factory=list)  # (listing, old price)
    warnings: list[SourceRun] = field(default_factory=list)
    page_url: str | None = None

    def is_empty(self) -> bool:
        return not (self.new or self.drops or self.warnings)

    def summary(self) -> str | None:
        lines: list[str] = []
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
    outcomes: Sequence[RunOutcome], store: Store, page_url: str | None = None
) -> Digest:
    new = truly_new([item for o in outcomes for item in o.new_matches])
    drops = []
    for o in outcomes:
        for item in o.price_drops:
            if len(item.price_history) >= 2:
                drops.append((item, item.price_history[-2].price_eur))
    return Digest(
        new=new, drops=drops, warnings=failing_sources(store, outcomes), page_url=page_url
    )


class Telegram:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.client = client or httpx.Client(timeout=20)

    @classmethod
    def from_env(cls) -> Telegram | None:
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        return cls(token, chat) if token and chat else None

    def _post(self, method: str, payload: dict[str, object]) -> None:
        resp = self.client.post(f"{self.base}/{method}", json={"chat_id": self.chat_id, **payload})
        resp.raise_for_status()

    def send(self, digest: Digest) -> int:
        """Send the digest; returns how many messages went out."""
        sent = 0
        summary = digest.summary()
        if summary:
            self._post(
                "sendMessage",
                {"text": summary, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            sent += 1
        for listing in digest.new[:MAX_PHOTO_MESSAGES]:
            text = caption(listing)
            if listing.photos:
                self._post(
                    "sendPhoto", {"photo": listing.photos[0], "caption": text, "parse_mode": "HTML"}
                )
            else:
                self._post(
                    "sendMessage",
                    {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                )
            sent += 1
        return sent


def notify(outcomes: Sequence[RunOutcome], store: Store, telegram: Telegram | None) -> int:
    if telegram is None:
        log.info("Telegram not configured; skipping digest")
        return 0
    digest = build_digest(outcomes, store, os.environ.get("PAGE_URL"))
    if digest.is_empty():
        return 0
    try:
        return telegram.send(digest)
    except httpx.HTTPError as exc:
        # Never leak the bot token (it's in the URL) into logs.
        log.warning("Telegram send failed: %s", type(exc).__name__)
        return 0
