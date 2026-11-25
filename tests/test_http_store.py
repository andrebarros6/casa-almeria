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
