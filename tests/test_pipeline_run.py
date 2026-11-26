from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scraper import run as run_module
from scraper.config import SearchSpec
from scraper.http import SourceBlocked
from scraper.models import Listing, Stub
from scraper.pipeline import run_source
from scraper.sources import select
from scraper.store import JsonStore

from .conftest import make_listing

NOW = datetime(2026, 11, 25, 7, tzinfo=UTC)


class FakeSource:
    name = "fake"
    runs_on = "cloud"

    def __init__(
        self,
        stubs: list[Stub],
        details: dict[str, Listing],
        search_error: Exception | None = None,
        detail_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.stubs, self.details = stubs, details
        self.search_error = search_error
        self.detail_errors = detail_errors or {}
        self.detail_calls: list[str] = []

    def search(self, spec: SearchSpec) -> list[Stub]:
        if self.search_error:
            raise self.search_error
        return self.stubs

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        self.detail_calls.append(stub.source_id)
        if stub.source_id in self.detail_errors:
            raise self.detail_errors[stub.source_id]
        return self.details[stub.source_id].model_copy(update={"price_eur": stub.price_eur})


def stub(sid: str, price: int = 800) -> Stub:
    return Stub(source="fake", source_id=sid, url=f"https://x.test/{sid}", price_eur=price)


def listing(sid: str, **kw: object) -> Listing:
    return make_listing(source="fake", source_id=sid, **kw)


def test_new_listings_are_filtered_and_stored(spec: SearchSpec) -> None:
    store = JsonStore()
    src = FakeSource(
        [stub("1"), stub("2"), stub("3", 1200)],
        {
            "1": listing("1"),
            "2": listing("2", description="alquiler de temporada"),
            "3": listing("3"),
        },
    )
    out = run_source(src, spec, store, now=NOW)
    assert out.run.status == "ok"
    assert (out.run.found, out.run.new, out.run.new_matches) == (3, 3, 1)
    assert [item.id for item in out.new_matches] == ["fake:1"]
    saved = store.get_many(["fake:1", "fake:2", "fake:3"])
    assert saved["fake:1"].group_id == "fake:1"
    assert saved["fake:1"].first_seen == NOW
    assert saved["fake:2"].rejected_reason is not None
    assert (
        saved["fake:3"].rejected_reason is not None and "price" in saved["fake:3"].rejected_reason
    )
    assert store.runs[-1].finished_at is not None


def test_second_run_skips_detail_and_tracks_price_drop(spec: SearchSpec) -> None:
    store = JsonStore()
    details = {"1": listing("1"), "2": listing("2", lat=37.0)}
    run_source(FakeSource([stub("1", 900), stub("2", 1100)], details), spec, store, now=NOW)

    later = NOW + timedelta(days=1)
    src = FakeSource([stub("1", 850), stub("2", 990)], details)
    out = run_source(src, spec, store, now=later)
    assert src.detail_calls == []
    assert out.run.updated == 2 and out.run.new == 0
    assert [item.id for item in out.price_drops] == ["fake:1"]
    # fake:2 was rejected on price; dropping under budget makes it a new match
    assert [item.id for item in out.new_matches] == ["fake:2"]
    saved = store.get_many(["fake:1"])["fake:1"]
    assert [p.price_eur for p in saved.price_history] == [900, 850]
    assert saved.last_seen == later


def test_cross_portal_duplicate_joins_group(spec: SearchSpec) -> None:
    store = JsonStore()
    store.upsert([make_listing(source="other", source_id="9", group_id="other:9", last_seen=NOW)])
    out = run_source(FakeSource([stub("1")], {"1": listing("1")}), spec, store, now=NOW)
    assert out.new_matches[0].group_id == "other:9"


def test_listings_go_stale_after_successful_run(spec: SearchSpec) -> None:
    store = JsonStore()
    run_source(FakeSource([stub("1")], {"1": listing("1")}), spec, store, now=NOW)
    later = NOW + timedelta(days=4)
    out = run_source(FakeSource([], {}), spec, store, now=later)
    assert out.run.gone == 1
    assert store.get_many(["fake:1"])["fake:1"].gone
    # It reappears: un-gone
    run_source(FakeSource([stub("1")], {"1": listing("1")}), spec, store, now=later)
    assert not store.get_many(["fake:1"])["fake:1"].gone


@pytest.mark.parametrize(
    ("error", "status"), [(SourceBlocked("403"), "blocked"), (RuntimeError("boom"), "error")]
)
def test_search_failure_is_recorded_and_nothing_expires(
    spec: SearchSpec, error: Exception, status: str
) -> None:
    store = JsonStore()
    store.upsert([listing("1", last_seen=NOW - timedelta(days=10))])
    out = run_source(FakeSource([], {}, search_error=error), spec, store, now=NOW)
    assert out.run.status == status and out.run.error
    assert not store.get_many(["fake:1"])["fake:1"].gone
    assert store.runs[-1].status == status


def test_detail_errors(spec: SearchSpec) -> None:
    store = JsonStore()
    src = FakeSource(
        [stub("1"), stub("2"), stub("3")],
        {"1": listing("1"), "3": listing("3", lat=37.0)},
        detail_errors={"2": SourceBlocked("captcha")},
    )
    out = run_source(src, spec, store, now=NOW)
    assert out.run.status == "blocked"
    assert src.detail_calls == ["1", "2"]  # stops after the block
    assert store.get_many(["fake:1"])  # but keeps what it got

    src2 = FakeSource(
        [stub("4"), stub("5")],
        {"5": listing("5", lat=37.1)},
        detail_errors={"4": ValueError("bad html")},
    )
    out2 = run_source(src2, spec, JsonStore(), now=NOW)
    assert out2.run.status == "ok" and out2.run.new == 1


def test_max_details_caps_and_skips_expiry(spec: SearchSpec) -> None:
    store = JsonStore()
    store.upsert([listing("old", last_seen=NOW - timedelta(days=10))])
    details = {str(i): listing(str(i), lat=36.0 + i) for i in range(5)}
    src = FakeSource([stub(str(i)) for i in range(5)], details)
    out = run_source(src, spec, store, now=NOW, max_details=2)
    assert len(src.detail_calls) == 2
    assert out.run.gone == 0


# --- registry + CLI -------------------------------------------------------


def test_select_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALERTS_EMAIL", raising=False)
    assert [s.name for s in select("all")] == ["pisos", "enalquiler", "fotocasa"]
    assert [s.name for s in select("cloud")] == ["pisos", "enalquiler"]
    assert [s.name for s in select("local")] == ["fotocasa"]
    assert [s.name for s in select("pisos")] == ["pisos"]
    with pytest.raises(ValueError, match="nope"):
        select("pisos,nope")


def test_cli_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSource([stub("1")], {"1": listing("1")})
    monkeypatch.setattr(run_module, "select", lambda which: [fake])
    monkeypatch.setattr(run_module, "DRY_RUN_FILE", tmp_path / "l.json")
    monkeypatch.setattr(run_module, "ENV_FILE", tmp_path / "none.env")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert run_module.main(["--max-details", "5"]) == 0
    out = capsys.readouterr().out
    assert "matches=1" in out and "regroup      merged=0 cards" in out
    assert (tmp_path / "l.json").exists()

    blocked = FakeSource([], {}, search_error=SourceBlocked("x"))
    monkeypatch.setattr(run_module, "select", lambda which: [blocked])
    assert run_module.main(["--dry-run", "--max-details", "0"]) == 1


def test_cli_uses_supabase_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class FakeSupabase(JsonStore):
        @classmethod
        def from_env(cls) -> FakeSupabase:
            created.append("yes")
            return cls()

    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setattr(run_module, "ENV_FILE", Path("none.env"))
    monkeypatch.setattr(run_module, "SupabaseStore", FakeSupabase)
    monkeypatch.setattr(run_module, "select", lambda which: [])
    sent: list[int] = []

    def fake_notify(outcomes: list[object], store: object, telegram: object) -> int:
        sent.append(len(outcomes))
        return 0

    monkeypatch.setattr(run_module, "notify", fake_notify)
    assert run_module.main([]) == 0
    assert created == ["yes"]
    assert sent == [0]  # real runs notify by default
    assert run_module.main(["--no-notify"]) == 0
    assert sent == [0]


def test_load_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        '# comment\n\nNEW_KEY="abc"\nEXISTING=from_file\nbroken line\nEMPTY=\n', encoding="utf-8"
    )
    monkeypatch.delenv("NEW_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from_shell")
    run_module.load_env_file(env)
    import os

    assert os.environ["NEW_KEY"] == "abc"
    assert os.environ["EXISTING"] == "from_shell"
    monkeypatch.delenv("NEW_KEY")
    run_module.load_env_file(tmp_path / "missing.env")


def test_free_details_ignore_the_cap(spec: SearchSpec) -> None:
    details = {str(i): listing(str(i), lat=36.0 + i) for i in range(5)}
    src = FakeSource([stub(str(i)) for i in range(5)], details)
    src.free_details = True  # type: ignore[attr-defined]
    out = run_source(src, spec, JsonStore(), now=NOW, max_details=2)
    assert len(src.detail_calls) == 5
    assert out.run.new == 5


def test_known_listings_are_refiltered_when_config_changes(spec: SearchSpec) -> None:
    store = JsonStore()
    details = {"1": listing("1", description="piso compartido")}
    spec.room_share_blocklist = []
    out = run_source(FakeSource([stub("1")], details), spec, store, now=NOW)
    assert out.run.new_matches == 1
    spec.room_share_blocklist = ["piso compartido"]
    run_source(FakeSource([stub("1")], details), spec, store, now=NOW + timedelta(days=1))
    reason = store.get_many(["fake:1"])["fake:1"].rejected_reason
    assert reason is not None and reason.startswith("room share")
