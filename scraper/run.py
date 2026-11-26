"""CLI entry point: python -m scraper.run --sources cloud|local|all|<names> [--dry-run]."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from scraper.config import load_spec
from scraper.dedupe import regroup
from scraper.notify import Telegram, notify
from scraper.pipeline import RunOutcome, run_source
from scraper.sources import select
from scraper.store import JsonStore, Store, SupabaseStore
from scraper.summary import build_summary

DRY_RUN_FILE = Path("out/listings.json")
ENV_FILE = Path(".env")


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv: list[str] | None = None) -> int:
    load_env_file(ENV_FILE)
    parser = argparse.ArgumentParser(description="Collect Almería rental listings.")
    parser.add_argument("--sources", default="all")
    parser.add_argument(
        "--dry-run", action="store_true", help=f"store in {DRY_RUN_FILE} instead of Supabase"
    )
    parser.add_argument("--max-details", type=int, default=None)
    parser.add_argument(
        "--notify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="send the Telegram digest (default: on for real runs, off for --dry-run)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO; Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    spec = load_spec()
    if args.dry_run or not os.environ.get("SUPABASE_URL"):
        if not args.dry_run:
            print("SUPABASE_URL not set; using dry-run JSON store", file=sys.stderr)
        store: Store = JsonStore(DRY_RUN_FILE)
    else:
        store = SupabaseStore.from_env()

    outcomes: list[RunOutcome] = []
    for source in select(args.sources):
        kwargs = {"max_details": args.max_details} if args.max_details is not None else {}
        outcome = run_source(source, spec, store, **kwargs)
        outcomes.append(outcome)
        r = outcome.run
        print(
            f"{r.source:<12} {r.status:<8} found={r.found} new={r.new} "
            f"matches={r.new_matches} updated={r.updated} gone={r.gone}"
            + (f" error={r.error}" if r.error else "")
        )

    regrouping = regroup(store.active_listings())
    if regrouping.changed:
        store.upsert(regrouping.changed)
        store.move_reactions(regrouping.moves)
    print(f"regroup      merged={len(regrouping.moves)} cards")
    store.save_summary(build_summary(spec, store.current_reasons(), datetime.now(UTC)))

    should_notify = args.notify if args.notify is not None else not args.dry_run
    if should_notify:
        sent = notify(outcomes, store, Telegram.from_env())
        print(f"telegram     sent={sent}")

    return 0 if all(o.run.status == "ok" for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
