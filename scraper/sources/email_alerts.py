"""Listings from portal alert emails (Idealista, yaencontre, Milanuncios).

These portals block automated browsing, but all of them email saved-search alerts.
A dedicated Gmail account receives the alerts and this source reads it over IMAP
(ALERTS_EMAIL + ALERTS_APP_PASSWORD). Each run re-reads the last WINDOW_DAYS of
alerts, so a listing stays "seen" while its email is in the window and expires
normally (spec.stale_after_days) after that.

Alert emails carry no feature data (lift, A/C...), so listings are marked
features_known=False: the must-have filter is skipped and the page shows them
as "check features".

The link patterns below are a first version; tune them against real alert
emails saved under tests/fixtures/email/.
"""

from __future__ import annotations

import email
import email.policy
import html as html_lib
import imaplib
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from scraper.config import SearchSpec
from scraper.models import Listing, Stub

WINDOW_DAYS = 21
IMAP_HOST = "imap.gmail.com"


@dataclass(frozen=True)
class Portal:
    name: str
    sender_domain: str
    link_re: re.Pattern[str]
    base: str


PORTALS = {
    "idealista": Portal(
        "idealista",
        "idealista.com",
        re.compile(r"https?://(?:www\.)?idealista\.com/inmueble/(\d+)/?"),
        "https://www.idealista.com/inmueble/{id}/",
    ),
    "yaencontre": Portal(
        "yaencontre",
        "yaencontre.com",
        re.compile(r"https?://(?:www\.)?yaencontre\.com/alquiler/[a-z-]+/inmueble-([\d-]+)"),
        "https://www.yaencontre.com/alquiler/piso/inmueble-{id}",
    ),
    "milanuncios": Portal(
        "milanuncios",
        "milanuncios.com",
        re.compile(r"https?://(?:www\.)?milanuncios\.com/[a-z0-9/-]*?-(\d{6,})\.htm"),
        "https://www.milanuncios.com/anuncio/-{id}.htm",
    ),
}

PRICE_RE = re.compile(r"(\d{1,2}[.\s]?\d{3}|\d{3,4})\s*(?:€|&euro;|eur\b)", re.IGNORECASE)
ROOMS_RE = re.compile(r"(\d)\s*(?:hab|dorm)", re.IGNORECASE)
AREA_RE = re.compile(r"(\d{2,3})\s*m(?:²|2|&sup2;)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def _body_text(msg: EmailMessage) -> str:
    """Prefer the HTML part (links live there); fall back to plain text."""
    for content_type in ("text/html", "text/plain"):
        part = msg.get_body(preferencelist=(content_type.split("/")[1],))
        if part is None:
            continue
        try:
            content = part.get_content()
        except (AttributeError, LookupError, ValueError):  # empty or malformed part
            continue
        if isinstance(content, str):
            return content
    return ""


def parse_alert(raw_html: str, portal: Portal) -> list[Listing]:
    """Extract listings from one alert email body.

    For each listing link, look at the text that follows it (up to the next listing
    link) for a price, bedrooms and m². Links without a nearby price are skipped.
    """
    text = html_lib.unescape(raw_html)
    matches = list(portal.link_re.finditer(text))
    found: dict[str, Listing] = {}
    for i, match in enumerate(matches):
        listing_id = match.group(1)
        if listing_id in found:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else match.end() + 1500
        window = TAG_RE.sub(" ", text[match.end() : end])
        price = PRICE_RE.search(window)
        if not price:
            continue
        rooms = ROOMS_RE.search(window)
        area = AREA_RE.search(window)
        title = " ".join(window.split())[:120]
        found[listing_id] = Listing(
            source=portal.name,
            source_id=listing_id,
            url=portal.base.format(id=listing_id),
            title=title or f"Anuncio {portal.name}",
            price_eur=int(re.sub(r"[^\d]", "", price.group(1))),
            bedrooms=int(rooms.group(1)) if rooms else None,
            area_m2=int(area.group(1)) if area else None,
            features_known=False,
        )
    return list(found.values())


MailboxReader = Callable[[str, datetime], Iterable[EmailMessage]]


def imap_reader(sender_domain: str, since: datetime) -> Iterable[EmailMessage]:  # pragma: no cover
    user, password = os.environ["ALERTS_EMAIL"], os.environ["ALERTS_APP_PASSWORD"]
    with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        criteria = f'(FROM "{sender_domain}" SINCE {since.strftime("%d-%b-%Y")})'
        _, data = imap.search(None, criteria)
        for num in data[0].split():
            _, parts = imap.fetch(num, "(RFC822)")
            for part in parts:
                if isinstance(part, tuple):
                    msg = email.message_from_bytes(part[1], policy=email.policy.default)
                    if isinstance(msg, EmailMessage):
                        yield msg


class EmailAlertsSource:
    runs_on = "cloud"
    free_details = True

    def __init__(self, portal: str, reader: MailboxReader = imap_reader) -> None:
        self.portal = PORTALS[portal]
        self.name = portal
        self.reader = reader
        self._parsed: dict[str, Listing] = {}

    def search(self, spec: SearchSpec) -> list[Stub]:
        since = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
        self._parsed = {}
        for msg in self.reader(self.portal.sender_domain, since):
            for listing in parse_alert(_body_text(msg), self.portal):
                self._parsed.setdefault(listing.source_id, listing)
        return [
            Stub(
                source=self.name,
                source_id=item.source_id,
                url=item.url,
                price_eur=item.price_eur,
                title=item.title,
            )
            for item in self._parsed.values()
        ]

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        listing = self._parsed[stub.source_id].model_copy(deep=True)
        listing.price_eur = stub.price_eur
        return listing


def email_sources_enabled() -> bool:
    return bool(os.environ.get("ALERTS_EMAIL") and os.environ.get("ALERTS_APP_PASSWORD"))
