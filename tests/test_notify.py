from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from scraper.models import Lead, PricePoint
from scraper.notify import (
    MAX_PHOTO_MESSAGES,
    Digest,
    Telegram,
    build_digest,
    build_nudges,
    caption,
    catch_line,
    failing_sources,
    notify,
    place,
    truly_new,
    when_text,
)
from scraper.pipeline import RunOutcome
from scraper.store import JsonStore, SourceRun

from .conftest import make_listing

NOW = datetime(2026, 11, 25, 7, tzinfo=UTC)


def outcome(source: str = "pisos", status: str = "ok", **kw: object) -> RunOutcome:
    return RunOutcome(run=SourceRun(source=source, started_at=NOW, status=status), **kw)  # type: ignore[arg-type]


# --- formatting -----------------------------------------------------------


def test_caption_reads_like_a_text() -> None:
    listing = make_listing(
        price_eur=850,
        bedrooms=3,
        area_m2=95,
        municipality="Almería",
        neighbourhood="Zapillo",
        features={"ac", "furnished", "storage"},
        url="https://www.pisos.com/x?a=1&b=2",
    )
    text = caption(listing)
    assert text.splitlines() == [
        "<b>850 € · 3 quartos · 95 m²</b>",
        "sem elevador",
        "Zapillo, Almería",
        "ar cond. · mobilado",
        '<a href="https://www.pisos.com/x?a=1&amp;b=2">Abrir anúncio</a> (pisos.com)',
    ]


def test_caption_escapes_portal_text_and_handles_gaps() -> None:
    listing = make_listing(
        bedrooms=1,
        area_m2=None,
        neighbourhood="<b>x</b>",
        municipality=None,
        features=set(),
        features_known=False,
        source="weird",
    )
    text = caption(listing)
    assert "1 quarto" in text and "&lt;b&gt;x&lt;/b&gt;" in text
    assert "confirmar extras" in text and "(weird)" in text


def test_catch_line_and_place() -> None:
    assert catch_line(make_listing(features={"elevator", "ac"})) == ""
    assert catch_line(make_listing(property_type="house", features=set())) == "sem ar condicionado"
    assert place(make_listing(municipality="Vera", neighbourhood="Vera")) == "Vera"
    assert place(make_listing(municipality=None, neighbourhood=None)) == ""


def test_truly_new_skips_cross_portal_repeats() -> None:
    fresh = make_listing(source_id="1", group_id="pisos:1")
    repeat = make_listing(source="fotocasa", source_id="9", group_id="pisos:1")
    ungrouped = make_listing(source_id="2", group_id=None)
    assert [x.id for x in truly_new([fresh, repeat, ungrouped, fresh])] == ["pisos:1", "pisos:2"]


# --- digest ---------------------------------------------------------------


def test_failing_sources_warns_exactly_on_the_second_failure() -> None:
    store = JsonStore()

    def record(status: str, days_ago: int) -> None:
        store.record_run(
            SourceRun(source="fotocasa", started_at=NOW - timedelta(days=days_ago), status=status)
        )

    record("ok", 3)
    record("blocked", 1)
    assert failing_sources(store, [outcome("fotocasa", "blocked")]) == []  # first failure
    record("blocked", 0)
    warned = failing_sources(store, [outcome("fotocasa", "blocked")])
    assert [r.source for r in warned] == ["fotocasa"]
    record("blocked", -1)
    assert failing_sources(store, [outcome("fotocasa", "blocked")]) == []  # already warned
    assert failing_sources(store, [outcome("pisos")]) == []


def test_summary_lists_counts_drops_and_warnings() -> None:
    drop = make_listing(municipality="Almería", neighbourhood="Zapillo", price_eur=800)
    digest = Digest(
        new=[make_listing(source_id=str(i)) for i in range(MAX_PHOTO_MESSAGES + 2)],
        drops=[(drop, 850)],
        warnings=[
            SourceRun(source="fotocasa", started_at=NOW, status="blocked"),
            SourceRun(source="pisos", started_at=NOW, status="error"),
        ],
        page_url="https://me.github.io/casa/",
    )
    text = digest.summary()
    assert text is not None
    assert "<b>12 novos hoje.</b>" in text
    assert "+2 mais na página." in text
    assert "Zapillo, Almería</a>: 850 € → 800 €" in text
    assert "Fotocasa falhou 2 vezes seguidas (bloqueado). Vê se o PC está ligado." in text
    assert "pisos.com falhou 2 vezes seguidas (erro)." in text
    assert text.endswith('<a href="https://me.github.io/casa/">Ver na página</a>')
    assert Digest(new=[make_listing()]).summary() == "<b>1 novo hoje.</b>"
    assert Digest().summary() is None and Digest().is_empty()


def test_build_digest_from_outcomes() -> None:
    dropped = make_listing(source_id="5", group_id="pisos:5", price_eur=800)
    dropped.price_history = [
        PricePoint(at=NOW - timedelta(days=1), price_eur=850),
        PricePoint(at=NOW, price_eur=800),
    ]
    no_history = make_listing(source_id="6")
    digest = build_digest(
        [
            outcome(
                new_matches=[make_listing(group_id="pisos:1")], price_drops=[dropped, no_history]
            ),
            outcome("fotocasa", new_matches=[make_listing(source="fotocasa", group_id="pisos:1")]),
        ],
        JsonStore(),
        page_url=None,
    )
    assert [x.id for x in digest.new] == ["pisos:1"]
    assert digest.drops == [(dropped, 850)]


# --- sending --------------------------------------------------------------


class Recorder:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(self.status, json={"ok": self.status == 200})


def _telegram(rec: Recorder) -> Telegram:
    return Telegram("TOKEN", "-100", client=httpx.Client(transport=httpx.MockTransport(rec)))


def test_send_summary_then_photos_capped() -> None:
    rec = Recorder()
    new = [make_listing(source_id=str(i), photos=["https://img/1.jpg"]) for i in range(12)]
    new[0].photos = []
    sent = _telegram(rec).send(Digest(new=new))
    assert sent == 1 + MAX_PHOTO_MESSAGES
    methods = [m for m, _ in rec.calls]
    assert methods[0] == "sendMessage" and methods[1] == "sendMessage"  # summary, then no-photo
    assert methods[2:] == ["sendPhoto"] * (MAX_PHOTO_MESSAGES - 1)
    assert all(body["chat_id"] == "-100" for _, body in rec.calls)
    assert rec.calls[2][1]["parse_mode"] == "HTML"


def test_notify_skips_without_config_or_content(monkeypatch: pytest.MonkeyPatch) -> None:
    assert notify([outcome(new_matches=[make_listing()])], JsonStore(), None) == 0
    rec = Recorder()
    assert notify([outcome()], JsonStore(), _telegram(rec)) == 0
    assert rec.calls == []
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert Telegram.from_env() is None
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    assert Telegram.from_env() is not None


def test_notify_sends_and_survives_telegram_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PAGE_URL", "https://me.github.io/casa/")
    ok = Recorder()
    assert notify([outcome(new_matches=[make_listing(photos=[])])], JsonStore(), _telegram(ok)) == 2
    assert "Ver na página" in str(ok.calls[0][1]["text"])

    broken = Recorder(status=401)
    with caplog.at_level(logging.WARNING):
        assert notify([outcome(new_matches=[make_listing()])], JsonStore(), _telegram(broken)) == 0
    assert "TOKEN" not in caplog.text  # the token must never reach the logs
    assert "sendMessage 401" in caplog.text  # ...but the status is there to debug with


def test_telegram_reason_is_logged_and_bad_photo_falls_back_to_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "sendPhoto":
            return httpx.Response(400, json={"ok": False, "description": "wrong file identifier"})
        return httpx.Response(200, json={"ok": True})

    tg = Telegram("TOKEN", "-100", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.WARNING):
        sent = tg.send(Digest(new=[make_listing(photos=["https://img/x.jpg"])]))
    assert sent == 2
    assert calls == ["sendMessage", "sendPhoto", "sendMessage"]
    assert "sendPhoto 400 wrong file identifier" in caplog.text
    assert "TOKEN" not in caplog.text


def test_one_failed_flat_does_not_stop_the_rest(caplog: pytest.LogCaptureFixture) -> None:
    n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        if n == 2:  # first flat: photo fails, then its text fallback fails too
            return httpx.Response(400, json={"description": "no"})
        if n == 3:
            return httpx.Response(500, text="not json")
        return httpx.Response(200, json={"ok": True})

    tg = Telegram("TOKEN", "-100", client=httpx.Client(transport=httpx.MockTransport(handler)))
    new = [make_listing(source_id=str(i), photos=["https://img/x.jpg"]) for i in range(2)]
    with caplog.at_level(logging.WARNING):
        assert tg.send(Digest(new=new)) == 2  # summary + the second flat
    assert "Telegram message skipped: sendMessage 500" in caplog.text


def test_from_env_strips_stray_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc\r\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " -100\r\n")
    tg = Telegram.from_env()
    assert tg is not None
    assert tg.base.endswith("/botabc") and tg.chat_id == "-100"
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "\r\n")
    assert Telegram.from_env() is None


# --- lead nudges ----------------------------------------------------------


def _lead(group: str, stage: str, stage_at: datetime, next_at: datetime | None = None) -> Lead:
    return Lead(group_id=group, stage=stage, stage_at=stage_at, next_action_at=next_at)


MORNING = datetime(2026, 11, 26, 7, tzinfo=UTC)  # 08:00 in Madrid


def test_when_text_in_madrid_time() -> None:
    assert when_text(datetime(2026, 11, 26, 17, tzinfo=UTC), MORNING) == "hoje 18:00"
    assert when_text(datetime(2026, 11, 27, 8, tzinfo=UTC), MORNING) == "amanhã 09:00"
    assert when_text(datetime(2026, 11, 30, 8, tzinfo=UTC), MORNING) == "30/11 09:00"


def test_build_nudges_only_on_reminder_days_and_upcoming_visits() -> None:
    flat = make_listing(municipality="Almería", neighbourhood="Zapillo", price_eur=850)
    pairs = [
        (_lead("a", "contactado", MORNING - timedelta(days=2, hours=1)), flat),
        (_lead("b", "contactado", MORNING - timedelta(days=3, hours=1)), flat),  # day 3: quiet
        (_lead("c", "contactado", MORNING - timedelta(days=5, hours=1)), flat),
        (_lead("d", "visita", MORNING, MORNING + timedelta(hours=10)), flat),
        (_lead("e", "visita", MORNING, MORNING + timedelta(days=3)), flat),  # too far ahead
        (_lead("f", "visita", MORNING, None), flat),  # no date yet
        (_lead("g", "respondeu", MORNING), flat),
    ]
    lines = build_nudges(pairs, MORNING)
    assert len(lines) == 3
    assert lines[0].startswith("⏳ Sem resposta há 2 dias: <a href=")
    assert "Zapillo, Almería · 850 €" in lines[0]
    assert lines[1].startswith("⏳ Sem resposta há 5 dias")
    assert lines[2].startswith("📅 Visita hoje 18:00")


def test_notify_includes_nudges_only_when_asked() -> None:
    store = JsonStore()
    flat = make_listing(group_id="pisos:1")
    store.upsert([flat])
    store.leads = [_lead("pisos:1", "contactado", MORNING - timedelta(days=2, hours=1))]
    rec = Recorder()
    assert notify([outcome()], store, _telegram(rec)) == 0  # nothing new, nudges off
    assert notify([outcome()], store, _telegram(rec), include_nudges=True, now=MORNING) == 1
    text = str(rec.calls[0][1]["text"])
    assert text.startswith("<b>Para tratar:</b>\n⏳ Sem resposta há 2 dias")
    assert not Digest(nudges=["x"]).is_empty()
