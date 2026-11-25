from __future__ import annotations

import imaplib
import subprocess
from typing import Any

import httpx
import pytest

from scraper import check_setup as cs

URL = "https://abcdefghijklmnopqrst.supabase.co"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*cs.GITHUB_SECRETS]:
        monkeypatch.delenv(name, raising=False)


def set_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_x")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_x")


def fake_supabase(
    *,
    service_status: int = 200,
    people: list[dict[str, Any]] | None = None,
    auth: list[str] | None = None,
    anon_rows: bool = False,
) -> httpx.Client:
    people = (
        people
        if people is not None
        else [
            {"email": "a@x.pt", "display_name": "A"},
            {"email": "b@x.pt", "display_name": "B"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        secret = request.headers.get("apikey", "").startswith("sb_secret")
        path = request.url.path
        if path == "/auth/v1/admin/users":
            return httpx.Response(200, json={"users": [{"email": e} for e in (auth or [])]})
        if not secret:
            return httpx.Response(200, json=[{"x": 1}] if anon_rows else [])
        if service_status != 200:
            return httpx.Response(service_status, json={"code": "42501"})
        if path.endswith("/allowed_users"):
            return httpx.Response(200, json=people)
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def names(checks: list[cs.Check]) -> dict[str, bool]:
    return {c.name: c.ok for c in checks}


def test_supabase_missing_values_stop_early() -> None:
    checks = cs.check_supabase(fake_supabase())
    assert names(checks) == {
        "Supabase URL": False,
        "Supabase secret key": False,
        "Supabase publishable key": False,
    }
    assert "https://<project-ref>" in checks[0].line()


def test_supabase_grants_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    set_supabase(monkeypatch)
    checks = cs.check_supabase(fake_supabase(service_status=403))
    last = checks[-1]
    assert last.name == "Scraper can read/write tables" and not last.ok
    assert "listings (403)" in last.detail and "grant" in last.fix


def test_supabase_all_good(monkeypatch: pytest.MonkeyPatch) -> None:
    set_supabase(monkeypatch)
    checks = cs.check_supabase(fake_supabase(auth=["a@x.pt", "B@x.pt"]))
    assert all(c.ok for c in checks), [c.line() for c in checks]


def test_supabase_people_users_and_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    set_supabase(monkeypatch)
    checks = names(
        cs.check_supabase(
            fake_supabase(
                people=[{"email": "a@x.pt", "display_name": None}], auth=[], anon_rows=True
            )
        )
    )
    assert checks["Allowed users"] is False  # missing display name
    assert checks["Login accounts"] is False
    assert checks["Strangers see nothing"] is False


def test_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    (skipped,) = cs.check_telegram(client, send_test=False)
    assert skipped.optional and not skipped.ok and skipped.line().startswith("○")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1")
    assert names(cs.check_telegram(client, send_test=True)) == {
        "Telegram bot token": True,
        "Telegram test message": True,
    }


class FakeImap:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def __enter__(self) -> FakeImap:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if self.fail:
            raise imaplib.IMAP4.error("bad")

    def select(self, box: str, readonly: bool) -> None:
        return None

    def search(self, charset: None, criteria: str) -> tuple[str, list[bytes]]:
        return "OK", [b"1 2" if "idealista" in criteria else b""]


def test_gmail(monkeypatch: pytest.MonkeyPatch) -> None:
    assert cs.check_gmail()[0].optional
    monkeypatch.setenv("ALERTS_EMAIL", "x@gmail.com")
    monkeypatch.setenv("ALERTS_APP_PASSWORD", "pw")
    (ok,) = cs.check_gmail(lambda host: FakeImap())  # type: ignore[arg-type,return-value]
    assert ok.ok and "idealista 2" in ok.detail and "yaencontre 0" in ok.detail
    (bad,) = cs.check_gmail(lambda host: FakeImap(fail=True))  # type: ignore[arg-type,return-value]
    assert not bad.ok and "app password" in bad.fix


def runner(outputs: dict[str, tuple[int, str]]) -> cs.Runner:
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        code, out = outputs.get(cmd[0] + " " + cmd[1], (0, ""))
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr="")

    return run


def test_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "gh")
    (no_remote,) = cs.check_github(runner({"git remote": (2, "")}))
    assert not no_remote.ok and "origin" in no_remote.detail
    listed = "SUPABASE_URL\t2026\nSUPABASE_SERVICE_KEY\t2026\n"
    (partial,) = cs.check_github(runner({"gh secret": (0, listed)}))
    assert not partial.ok and "SUPABASE_ANON_KEY" in partial.detail
    assert "optional missing: TELEGRAM_BOT_TOKEN" in partial.detail
    every = "\n".join(f"{s}\tx" for s in cs.GITHUB_SECRETS)
    assert cs.check_github(runner({"gh secret": (0, every)}))[0].ok
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert not cs.check_github()[0].ok


def test_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    checks = names(cs.check_local(runner({"schtasks /query": (1, "")})))
    assert checks["Daily task on this PC"] is False
    assert "Playwright installed" in checks


def test_main_reports_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cs, "load_env_file", lambda path: None)
    monkeypatch.setattr(cs, "check_supabase", lambda client: [cs.Check("Supabase URL", False)])
    monkeypatch.setattr(cs, "check_telegram", lambda client, t: [])
    monkeypatch.setattr(cs, "check_gmail", lambda: [cs.Check("Alert Gmail", False, optional=True)])
    monkeypatch.setattr(cs, "check_github", lambda: [cs.Check("GitHub secrets", True)])
    monkeypatch.setattr(cs, "check_local", lambda: [])
    assert cs.main([]) == 1
    out = capsys.readouterr().out
    assert "✗ Supabase URL" in out and "○ Alert Gmail" in out and "1 required step(s) left." in out
    monkeypatch.setattr(cs, "check_supabase", lambda client: [cs.Check("Supabase URL", True)])
    assert cs.main([]) == 0
    assert "All required steps done." in capsys.readouterr().out


def test_single_user_is_enough_for_testing(monkeypatch: pytest.MonkeyPatch) -> None:
    set_supabase(monkeypatch)
    people = [{"email": "a@x.pt", "display_name": "A"}]
    checks = cs.check_supabase(fake_supabase(people=people, auth=["a@x.pt"]))
    allowed = next(c for c in checks if c.name == "Allowed users")
    assert allowed.ok and "add your partner" in allowed.detail
