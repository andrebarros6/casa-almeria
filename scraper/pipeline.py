"""One source run: search -> detail for new listings -> filter -> dedupe -> store."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from scraper.config import SearchSpec
from scraper.dedupe import assign_group
from scraper.filters import rejection_reason
from scraper.http import SourceBlocked
from scraper.models import Listing, PricePoint
from scraper.sources.base import Source
from scraper.store import SourceRun, Store

log = logging.getLogger(__name__)

MAX_DETAILS_PER_RUN = 300  # caps the first run; the rest is picked up the next day


@dataclass
class RunOutcome:
    run: SourceRun
    new_matches: list[Listing] = field(default_factory=list)
    price_drops: list[Listing] = field(default_factory=list)


def _update_known(listing: Listing, price: int, now: datetime, spec: SearchSpec) -> bool:
    """Refresh a known listing from its search card. Returns True if the price dropped."""
    dropped = False
    if listing.price_eur != price:
        dropped = price < listing.price_eur
        listing.price_history.append(PricePoint(at=now, price_eur=price))
        listing.price_eur = price
    # Re-filter every run, so config changes apply to listings already stored.
    listing.rejected_reason = rejection_reason(listing, spec)
    listing.gone = False
    listing.last_seen = now
    return dropped


def run_source(
    source: Source,
    spec: SearchSpec,
    store: Store,
    now: datetime | None = None,
    max_details: int = MAX_DETAILS_PER_RUN,
) -> RunOutcome:
    now = now or datetime.now(UTC)
    outcome = RunOutcome(run=SourceRun(source=source.name, started_at=now))
    run = outcome.run

    try:
        stubs = source.search(spec)
    except SourceBlocked as exc:
        run.status, run.error = "blocked", str(exc)
    except Exception as exc:
        log.exception("search failed for %s", source.name)
        run.status, run.error = "error", f"{type(exc).__name__}: {exc}"
    else:
        run.found = len(stubs)
        existing = store.get_many([s.id for s in stubs])
        candidates = store.active_listings()
        to_save: list[Listing] = []
        details_fetched = 0

        for stub in stubs:
            known = existing.get(stub.id)
            if known is not None:
                was_rejected = known.rejected_reason is not None
                dropped = _update_known(known, stub.price_eur, now, spec)
                if dropped and not was_rejected and known.rejected_reason is None:
                    outcome.price_drops.append(known)
                if was_rejected and known.rejected_reason is None:
                    known.group_id = assign_group(known, candidates)
                    outcome.new_matches.append(known)
                run.updated += 1
                to_save.append(known)
                continue

            if not getattr(source, "free_details", False):
                if details_fetched >= max_details:
                    continue
                details_fetched += 1
            try:
                listing = source.fetch_detail(stub, spec)
            except SourceBlocked as exc:
                run.status, run.error = "blocked", str(exc)
                break
            except Exception as exc:
                log.warning("detail failed for %s: %s", stub.url, exc)
                continue

            listing.first_seen = listing.last_seen = now
            listing.price_history = [PricePoint(at=now, price_eur=listing.price_eur)]
            listing.rejected_reason = rejection_reason(listing, spec)
            run.new += 1
            if listing.rejected_reason is None:
                listing.group_id = assign_group(listing, candidates)
                candidates.append(listing)
                outcome.new_matches.append(listing)
            to_save.append(listing)

        store.upsert(to_save)
        run.new_matches = len(outcome.new_matches)
        # Only expire listings after a complete, successful run of this source.
        if run.status == "ok" and details_fetched < max_details:
            run.gone = store.mark_gone(source.name, now - timedelta(days=spec.stale_after_days))

    run.finished_at = datetime.now(UTC)
    store.record_run(run)
    return outcome
