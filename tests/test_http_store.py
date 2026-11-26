from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scraper.http import Fetcher, SourceBlocked
from scraper.store import JsonStore, SourceRun, SupabaseStore

from .conftest import make_listing

NOW = datetime(2026, 11, 25, 7, tzinfo=UTC)

# --- Fetcher --------------------------------------------------------------


def _fetcher(handler: httpx.MockTransport, sleeps: list[float]) -> Fetcher:
    return Fetcher(
        min_delay=1, max_delay=1, client=httpx.Client(transport=handler), sleep=sleeps.append
    )


def test_fetcher_returns_html_and_waits_between_requests() -> None:
    sleeps: list[float] = []
    f = _fetcher(httpx.MockTransport(lambda r: httpx.Response(200, text="<html>ok</html>")), sleeps)
    assert f.get("https://x.test/a") == "<html>ok</html>"
    assert f.get("https://x.test/b") == "<html>ok</html>"
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(429),
        httpx.Response(200, text='<script src="https://geo.captcha-delivery.com/x"></script>'),
    ],
)
def test_fetcher_detects_blocks(response: httpx.Response) -> None:
    f = _fetcher(httpx.MockTransport(lambda r: response), [])
    with pytest.raises(SourceBlocked):
        f.get("https://x.test/")


def test_fetcher_raises_on_server_error() -> None:
    f = _fetcher(httpx.MockTransport(lambda r: httpx.Response(500)), [])
    with pytest.raises(httpx.HTTPStatusError):
        f.get("https://x.test/")


def test_fetcher_default_client_has_spanish_headers() -> None:
    f = Fetcher()
    assert f.client.headers["Accept-Language"].startswith("es-ES")


# --- JsonStore ------------------------------------------------------------


def test_json_store_roundtrip_and_gone(tmp_path: Path) -> None:
    path = tmp_path / "out" / "listings.json"
    store = JsonStore(path)
    fresh = make_listing(source_id="1", last_seen=NOW)
    stale = make_listing(source_id="2", last_seen=NOW - timedelta(days=5))
    rejected = make_listing(source_id="3", last_seen=NOW, rejected_reason="price")
    other = make_listing(source="idealista", source_id="4", last_seen=NOW - timedelta(days=9))
    store.upsert([fresh, stale, rejected, other])
    store.record_run(SourceRun(source="pisos", started_at=NOW))

    assert store.mark_gone("pisos", NOW - timedelta(days=3)) == 1
    reloaded = JsonStore(path)
    assert reloaded.get_many(["pisos:2"])["pisos:2"].gone
    assert {item.id for item in reloaded.active_listings()} == {"pisos:1", "idealista:4"}
    assert reloaded.runs[0].source == "pisos"
    assert reloaded.get_many(["nope"]) == {}


def test_json_store_returns_copies() -> None:
    store = JsonStore()
    store.upsert([make_listing()])
    got = store.get_many(["pisos:1"])["pisos:1"]
    got.price_eur = 1
    assert store.get_many(["pisos:1"])["pisos:1"].price_eur == 800


# --- SupabaseStore --------------------------------------------------------


class Recorder:
    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.responses.get((request.method, request.url.path))
        if body is None:
            return httpx.Response(201)
        return httpx.Response(200, json=body)


def _supabase(rec: Recorder) -> SupabaseStore:
    return SupabaseStore(
        "https://db.test/", "secret", client=httpx.Client(transport=httpx.MockTransport(rec))
    )


def test_supabase_get_many_and_active() -> None:
    row = {**make_listing().model_dump(mode="json"), "id": "pisos:1", "features": ["elevator"]}
    rec = Recorder({("GET", "/rest/v1/listings"): [row]})
    store = _supabase(rec)
    assert store.get_many(["pisos:1"])["pisos:1"].features == {"elevator"}
    assert len(store.active_listings()) == 1
    first = rec.requests[0]
    assert first.headers["apikey"] == "secret"
    assert "authorization" not in first.headers  # not a JWT, so apikey only
    assert first.url.params["id"] == 'in.("pisos:1")'
    assert rec.requests[1].url.params["rejected_reason"] == "is.null"


def test_supabase_upsert_chunks_and_merges() -> None:
    rec = Recorder({})
    store = _supabase(rec)
    store.CHUNK = 2
    store.upsert([make_listing(source_id=str(i)) for i in range(3)])
    assert len(rec.requests) == 2
    assert "merge-duplicates" in rec.requests[0].headers["Prefer"]
    body = json.loads(rec.requests[0].content)
    assert body[0]["id"] == "pisos:0" and body[0]["features"] == ["elevator"]


def test_supabase_mark_gone_and_record_run() -> None:
    rec = Recorder({("PATCH", "/rest/v1/listings"): [{"id": "a"}, {"id": "b"}]})
    store = _supabase(rec)
    assert store.mark_gone("pisos", NOW) == 2
    assert rec.requests[0].url.params["source"] == "eq.pisos"
    store.record_run(SourceRun(source="pisos", started_at=NOW, status="blocked"))
    assert json.loads(rec.requests[1].content)["status"] == "blocked"


def test_supabase_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    assert SupabaseStore.from_env().base == "https://abc.supabase.co/rest/v1"


def test_recent_runs_newest_first() -> None:
    store = JsonStore()
    for days, status in ((2, "ok"), (0, "blocked"), (1, "error")):
        store.record_run(
            SourceRun(source="x", started_at=NOW - timedelta(days=days), status=status)
        )
    store.record_run(SourceRun(source="y", started_at=NOW))
    assert [r.status for r in store.recent_runs("x", 2)] == ["blocked", "error"]


def test_supabase_recent_runs() -> None:
    row = SourceRun(source="x", started_at=NOW, status="blocked").model_dump(mode="json")
    rec = Recorder({("GET", "/rest/v1/source_runs"): [row]})
    runs = _supabase(rec).recent_runs("x", 3)
    assert runs[0].status == "blocked"
    params = rec.requests[0].url.params
    assert (params["source"], params["order"], params["limit"]) == ("eq.x", "started_at.desc", "3")


@pytest.mark.parametrize(
    ("key", "bearer"), [("eyJhbGciOi.legacy.jwt", True), ("sb_secret_abc123", False)]
)
def test_supabase_auth_headers_by_key_type(key: str, bearer: bool) -> None:
    store = SupabaseStore("https://db.test", key)
    assert store.headers["apikey"] == key
    assert ("Authorization" in store.headers) is bearer


def test_json_store_summary_reasons_and_noop_moves(tmp_path: Path) -> None:
    store = JsonStore(tmp_path / "l.json")
    store.upsert(
        [
            make_listing(source_id="1"),
            make_listing(source_id="2", rejected_reason="price 1100 > 1000"),
            make_listing(source_id="3", rejected_reason="price 1200 > 1000", gone=True),
        ]
    )
    assert sorted(store.current_reasons(), key=str) == [None, "price 1100 > 1000"]
    store.save_summary({"counts": {"seen": 2}})
    store.move_reactions({"a": "b"})
    assert JsonStore(tmp_path / "l.json").listings  # reloads with a summary present


def test_merge_notes() -> None:
    from scraper.store import merge_notes

    assert merge_notes("gosto", "varanda") == "gosto / varanda"
    assert merge_notes("gosto", "gosto") == "gosto"
    assert merge_notes(None, " ") is None
    assert merge_notes(None, "x") == "x"


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_supabase_pages_past_the_row_limit() -> None:
    row = {**make_listing().model_dump(mode="json"), "id": "pisos:1", "features": []}
    offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offsets.append(request.url.params["offset"])
        full = int(request.url.params["offset"]) < 4
        return httpx.Response(200, json=[row] * (2 if full else 1))

    store = SupabaseStore("https://db.test", "k", client=_client(handler))
    store.PAGE = 2
    assert len(store.active_listings()) == 5
    assert offsets == ["0", "2", "4"]


def test_supabase_reasons_and_summary() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            rows = [{"id": "x", "rejected_reason": "price"}, {"id": "y", "rejected_reason": None}]
            return httpx.Response(200, json=rows)
        return httpx.Response(201)

    store = SupabaseStore("https://db.test", "k", client=_client(handler))
    assert store.current_reasons() == ["price", None]
    store.save_summary({"criteria": {}, "counts": {}, "updated_at": "t"})
    assert sent[-1].url.path.endswith("/search_summary")
    assert json.loads(sent[-1].content)["id"] == "latest"
    assert "merge-duplicates" in sent[-1].headers["Prefer"]


def test_supabase_moves_reactions_to_the_surviving_card() -> None:
    rows = {
        ("old", "a@x"): {"group_id": "old", "user_email": "a@x", "reaction": "like", "note": "bom"},
        ("old", "b@x"): {"group_id": "old", "user_email": "b@x", "reaction": None, "note": "caro"},
        ("new", "b@x"): {
            "group_id": "new",
            "user_email": "b@x",
            "reaction": "reject",
            "note": None,
        },
    }
    writes: list[tuple[str, dict[str, str], object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if request.method == "GET":
            group = params["group_id"].removeprefix("eq.")
            user = params.get("user_email", "").removeprefix("eq.")
            found = [r for (g, u), r in rows.items() if g == group and (not user or u == user)]
            return httpx.Response(200, json=found)
        body = json.loads(request.content) if request.content else None
        writes.append((request.method, params, body))
        return httpx.Response(204)

    SupabaseStore("https://db.test", "k", client=_client(handler)).move_reactions({"old": "new"})
    a_key = {"group_id": "eq.old", "user_email": "eq.a@x"}
    b_new = {"group_id": "eq.new", "user_email": "eq.b@x"}
    b_old = {"group_id": "eq.old", "user_email": "eq.b@x"}
    # a@x had nothing on the survivor: re-keyed. b@x had a reaction there: merged + old deleted.
    assert ("PATCH", a_key, {"group_id": "new"}) in writes
    assert ("PATCH", b_new, {"reaction": "reject", "note": "caro"}) in writes
    assert ("DELETE", b_old, None) in writes


def test_json_store_leads_with_listings() -> None:
    from scraper.models import Lead

    store = JsonStore()
    store.upsert(
        [
            make_listing(source_id="1", group_id="g1"),
            make_listing(source_id="2", group_id="g2", gone=True),
        ]
    )
    store.leads = [
        Lead(group_id="g1", stage="contactado", stage_at=NOW),
        Lead(group_id="g2", stage="contactado", stage_at=NOW),  # listing gone
        Lead(group_id="g1", stage="respondeu", stage_at=NOW),  # other stage
    ]
    pairs = store.leads_with_listings(["contactado"])
    assert [(lead.group_id, listing.id) for lead, listing in pairs] == [("g1", "pisos:1")]


def test_supabase_leads_with_listings() -> None:
    lead_row = {
        "group_id": "g1",
        "stage": "visita",
        "stage_at": NOW.isoformat(),
        "next_action_at": None,
    }
    listing_row = {
        **make_listing(group_id="g1").model_dump(mode="json"),
        "id": "pisos:1",
        "features": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/leads"):
            assert request.url.params["stage"] == "in.(contactado,visita)"
            return httpx.Response(200, json=[lead_row, {**lead_row, "group_id": "gone"}])
        return httpx.Response(200, json=[listing_row])

    store = SupabaseStore("https://db.test", "k", client=_client(handler))
    pairs = store.leads_with_listings(["contactado", "visita"])
    assert [(lead.group_id, listing.id) for lead, listing in pairs] == [("g1", "pisos:1")]

    empty = SupabaseStore(
        "https://db.test", "k", client=_client(lambda r: httpx.Response(200, json=[]))
    )
    assert empty.leads_with_listings(["visita"]) == []
