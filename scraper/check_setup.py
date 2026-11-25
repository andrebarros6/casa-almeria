"""Check every setup step and say exactly what's missing.

    python -m scraper.check_setup            # check everything
    python -m scraper.check_setup --telegram-test   # also send a test message

Never prints secrets: only whether values exist, counts and HTTP statuses.
"""

from __future__ import annotations

import argparse
import imaplib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from scraper.run import ENV_FILE, load_env_file

TABLES = ("listings", "source_runs", "reactions", "allowed_users")
GITHUB_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_ANON_KEY",
    "COMMUTE_ADDRESS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ALERTS_EMAIL",
    "ALERTS_APP_PASSWORD",
)
OPTIONAL = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERTS_EMAIL", "ALERTS_APP_PASSWORD"}
TASK_NAME = "Almeria rental finder"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    optional: bool = False

    def line(self) -> str:
        mark = "✓" if self.ok else ("○" if self.optional else "✗")
        text = f"{mark} {self.name}"
        if self.detail:
            text += f": {self.detail}"
        if not self.ok and self.fix:
            text += f"\n    → {self.fix}"
        return text


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


# --- Supabase -------------------------------------------------------------------


def check_supabase(client: httpx.Client) -> list[Check]:
    url, svc, anon = (
        env("SUPABASE_URL").rstrip("/"),
        env("SUPABASE_SERVICE_KEY"),
        env("SUPABASE_ANON_KEY"),
    )
    checks = [
        Check(
            "Supabase URL",
            url.startswith("https://") and url.endswith(".supabase.co"),
            fix="Set SUPABASE_URL=https://<project-ref>.supabase.co in .env",
        ),
        Check("Supabase secret key", bool(svc), fix="Set SUPABASE_SERVICE_KEY in .env"),
        Check("Supabase publishable key", bool(anon), fix="Set SUPABASE_ANON_KEY in .env"),
    ]
    if not all(c.ok for c in checks):
        return checks

    denied = []
    for table in TABLES:
        resp = client.get(f"{url}/rest/v1/{table}", params={"limit": "1"}, headers=_headers(svc))
        if resp.status_code != 200:
            denied.append(f"{table} ({resp.status_code})")
    checks.append(
        Check(
            "Scraper can read/write tables",
            not denied,
            ", ".join(denied),
            "Run the 'grant' lines from supabase/schema.sql in the SQL Editor",
        )
    )
    if denied:
        return checks

    people = client.get(
        f"{url}/rest/v1/allowed_users",
        params={"select": "email,display_name"},
        headers=_headers(svc),
    ).json()
    named = sum(1 for p in people if p.get("display_name"))
    checks.append(
        Check(
            "Allowed users",
            len(people) >= 1 and named == len(people),
            f"{len(people)} emails, {named} with a display name"
            + (" (add your partner when ready)" if len(people) == 1 else ""),
            "Insert emails + display names into allowed_users (last line of schema.sql)",
        )
    )
    users_resp = client.get(f"{url}/auth/v1/admin/users", headers=_headers(svc))
    auth_emails = (
        {u.get("email", "").lower() for u in users_resp.json().get("users", [])}
        if users_resp.status_code == 200
        else set()
    )
    matched = sum(1 for p in people if p["email"].lower() in auth_emails)
    checks.append(
        Check(
            "Login accounts",
            bool(people) and matched == len(people),
            f"{matched}/{len(people)} allowed emails have a Supabase Auth user",
            "Authentication → Users → Add user (same emails, tick Auto Confirm)",
        )
    )

    leaks = []
    for table in TABLES:
        resp = client.get(f"{url}/rest/v1/{table}", params={"limit": "1"}, headers=_headers(anon))
        if resp.status_code == 200 and resp.json():
            leaks.append(table)
    checks.append(
        Check(
            "Strangers see nothing",
            not leaks,
            ", ".join(leaks) and f"readable without login: {', '.join(leaks)}",
            "Re-run the row-level security part of supabase/schema.sql",
        )
    )
    return checks


# --- other services -------------------------------------------------------------


def check_telegram(client: httpx.Client, send_test: bool) -> list[Check]:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return [
            Check(
                "Telegram",
                False,
                "not configured",
                "See README 'Telegram digest' (optional, but recommended)",
                optional=True,
            )
        ]
    me = client.get(f"https://api.telegram.org/bot{token}/getMe")
    checks = [Check("Telegram bot token", me.status_code == 200, fix="Check TELEGRAM_BOT_TOKEN")]
    if me.status_code == 200 and send_test:
        resp = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": "Casa Almería ligada. Os anúncios novos chegam aqui."},
        )
        checks.append(
            Check(
                "Telegram test message",
                resp.status_code == 200,
                fix="Check TELEGRAM_CHAT_ID and that the bot is in the group",
            )
        )
    return checks


ImapFactory = Callable[[str], imaplib.IMAP4_SSL]


def check_gmail(imap_factory: ImapFactory = imaplib.IMAP4_SSL) -> list[Check]:
    user, password = env("ALERTS_EMAIL"), env("ALERTS_APP_PASSWORD")
    if not user or not password:
        return [
            Check(
                "Alert Gmail",
                False,
                "not configured",
                "See README 'Alert emails' (needed for Idealista, yaencontre, Milanuncios)",
                optional=True,
            )
        ]
    try:
        with imap_factory("imap.gmail.com") as imap:
            imap.login(user, password)
            imap.select("INBOX", readonly=True)
            since = (datetime.now(UTC) - timedelta(days=21)).strftime("%d-%b-%Y")
            counts = []
            for domain in ("idealista.com", "yaencontre.com", "milanuncios.com"):
                _, data = imap.search(None, f'(FROM "{domain}" SINCE {since})')
                counts.append(f"{domain.split('.')[0]} {len(data[0].split())}")
    except (imaplib.IMAP4.error, OSError) as exc:
        return [
            Check(
                "Alert Gmail login",
                False,
                type(exc).__name__,
                "Check ALERTS_EMAIL and the 16-character app password",
            )
        ]
    return [Check("Alert Gmail", True, "alerts in last 21 days: " + ", ".join(counts))]


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:  # pragma: no cover
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def check_github(runner: Runner = _run) -> list[Check]:
    if not shutil.which("gh"):
        return [Check("GitHub CLI", False, fix="Install GitHub CLI or add secrets in the website")]
    remote = runner(["git", "remote", "get-url", "origin"])
    if remote.returncode != 0:
        return [Check("GitHub repo", False, "no 'origin' remote yet", "Ask Claude to create it")]
    listed = runner(["gh", "secret", "list"])
    present = {line.split()[0] for line in listed.stdout.splitlines() if line.strip()}
    missing = [s for s in GITHUB_SECRETS if s not in present and s not in OPTIONAL]
    missing_opt = [s for s in GITHUB_SECRETS if s not in present and s in OPTIONAL]
    detail = f"missing: {', '.join(missing)}" if missing else ""
    if missing_opt:
        detail += ("; " if detail else "") + f"optional missing: {', '.join(missing_opt)}"
    return [Check("GitHub secrets", not missing, detail, "Ask Claude to upload them from .env")]


def check_local(runner: Runner = _run) -> list[Check]:
    checks = []
    try:
        import playwright  # noqa: F401

        checks.append(Check("Playwright installed", True))
    except ImportError:
        checks.append(
            Check("Playwright installed", False, fix='.venv\\Scripts\\pip install -e ".[local]"')
        )
    if sys.platform == "win32":
        task = runner(["schtasks", "/query", "/tn", TASK_NAME])
        checks.append(
            Check(
                "Daily task on this PC",
                task.returncode == 0,
                fix="Run the Register-ScheduledTask command in README 'PC sources'",
            )
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram-test", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ENV_FILE)
    if not Path(ENV_FILE).exists():
        print("✗ .env not found in the project folder")
        return 1
    client = httpx.Client(timeout=20)
    sections = {
        "Supabase": check_supabase(client),
        "Telegram": check_telegram(client, args.telegram_test),
        "Alert emails": check_gmail(),
        "GitHub": check_github(),
        "This PC": check_local(),
    }
    failed = 0
    for title, checks in sections.items():
        print(f"\n{title}")
        for check in checks:
            print("  " + check.line().replace("\n", "\n  "))
            failed += not check.ok and not check.optional
    print("\nAll required steps done." if not failed else f"\n{failed} required step(s) left.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
