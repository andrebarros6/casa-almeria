"""Email-alert source tests.

NOTE: these use SYNTHETIC emails modelled on typical alert layouts. Once the
dedicated Gmail receives real alerts, save them under tests/fixtures/email/ and
add tests against them. The link patterns may need adjusting.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from email.message import EmailMessage

import pytest

from scraper.config import SearchSpec
from scraper.filters import rejection_reason
from scraper.sources import EMAIL_SOURCES, select
from scraper.sources.email_alerts import (
    PORTALS,
    EmailAlertsSource,
    _body_text,
    email_sources_enabled,
    parse_alert,
)

IDEALISTA_HTML = """
<table>
 <tr><td><a href="https://www.idealista.com/inmueble/108765432/?xts=alert">
   Piso en calle Granada, Centro, Almer&iacute;a</a>
   <p>850 &euro;/mes</p><p>3 hab. 95 m&sup2; Planta 4&ordf; exterior con ascensor</p></td></tr>
 <tr><td><a href="https://www.idealista.com/inmueble/108765432/">Ver anuncio</a></td></tr>
 <tr><td><a href="https://www.idealista.com/inmueble/108700001/">
   Ático en Zapillo</a><p>1.150 €/mes</p><p>2 hab. 70 m²</p></td></tr>
 <tr><td><a href="https://www.idealista.com/inmueble/108799999/">Sin precio</a></td></tr>
</table>
"""

YAENCONTRE_HTML = (
    '<a href="https://www.yaencontre.com/alquiler/piso/inmueble-68407-113172342">'
    "Piso en El Zapillo</a> 800 € 3 habs. 85 m2"
)
MILANUNCIOS_HTML = (
    '<a href="https://www.milanuncios.com/alquiler-de-pisos-en-almeria-almeria/piso-123456789.htm">'
    "Piso Roquetas</a> 700 EUR 2 dormitorios"
)


def _msg(html: str | None = None, text: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "alertas@idealista.com"
    msg["Subject"] = "Nuevos pisos"
    if text is not None:
        msg.set_content(text)
    if html is not None:
        if text is None:
            msg.set_content("plain fallback")
        msg.add_alternative(html, subtype="html")
    return msg


def test_parse_idealista_alert() -> None:
    listings = parse_alert(IDEALISTA_HTML, PORTALS["idealista"])
    assert [item.source_id for item in listings] == ["108765432", "108700001"]
    first, second = listings
    assert first.url == "https://www.idealista.com/inmueble/108765432/"
    assert (first.price_eur, first.bedrooms, first.area_m2) == (850, 3, 95)
    assert "Piso en calle Granada" in first.title
    assert not first.features_known
    assert second.price_eur == 1150


def test_parse_other_portals() -> None:
    (ya,) = parse_alert(YAENCONTRE_HTML, PORTALS["yaencontre"])
    assert ya.source_id == "68407-113172342" and ya.price_eur == 800 and ya.bedrooms == 3
    (mil,) = parse_alert(MILANUNCIOS_HTML, PORTALS["milanuncios"])
    assert mil.source_id == "123456789" and mil.price_eur == 700 and mil.bedrooms == 2
    assert mil.area_m2 is None


def test_email_listings_skip_must_have_but_keep_other_filters(spec: SearchSpec) -> None:
    cheap, pricey = parse_alert(IDEALISTA_HTML, PORTALS["idealista"])
    assert rejection_reason(cheap, spec) is None  # no features, but not rejected
    assert rejection_reason(pricey, spec) is not None  # 1,150 € still over budget


def test_body_text_prefers_html_then_plain() -> None:
    assert "inmueble" in _body_text(_msg(html=IDEALISTA_HTML))
    assert _body_text(_msg(text="solo texto")).strip() == "solo texto"
    assert _body_text(EmailMessage()) == ""


def test_source_reads_mailbox_and_dedupes(spec: SearchSpec) -> None:
    calls: list[tuple[str, datetime]] = []

    def reader(domain: str, since: datetime) -> Iterable[EmailMessage]:
        calls.append((domain, since))
        return [_msg(html=IDEALISTA_HTML), _msg(html=IDEALISTA_HTML)]

    source = EmailAlertsSource("idealista", reader=reader)
    stubs = source.search(spec)
    assert calls[0][0] == "idealista.com"
    assert [s.source_id for s in stubs] == ["108765432", "108700001"]
    detail = source.fetch_detail(stubs[0].model_copy(update={"price_eur": 800}), spec)
    assert detail.price_eur == 800 and not detail.features_known
    assert source.name == "idealista" and source.runs_on == "cloud"


def test_email_sources_only_join_group_runs_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALERTS_EMAIL", raising=False)
    monkeypatch.delenv("ALERTS_APP_PASSWORD", raising=False)
    assert not email_sources_enabled()
    assert not EMAIL_SOURCES & {s.name for s in select("all")}
    assert [s.name for s in select("idealista")] == ["idealista"]  # explicit name still works

    monkeypatch.setenv("ALERTS_EMAIL", "x@gmail.com")
    monkeypatch.setenv("ALERTS_APP_PASSWORD", "pw")
    assert email_sources_enabled()
    assert {s.name for s in select("cloud")} >= EMAIL_SOURCES
