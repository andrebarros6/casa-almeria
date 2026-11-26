"""What the page shows at the top: the search criteria and how many listings each rule removed."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from scraper.config import SearchSpec

# rejected_reason prefix -> key the page translates. Order = display order.
REASON_KEYS = (
    ("short-term", "short_term"),
    ("price", "price"),
    ("must-have", "must_have"),
    ("room share", "room_share"),
    ("bedrooms", "bedrooms"),
    ("type", "type"),
)


def reason_key(reason: str) -> str:
    for prefix, key in REASON_KEYS:
        if reason.startswith(prefix):
            return key
    return "other"


def build_summary(
    spec: SearchSpec,
    reasons: Iterable[str | None],
    now: datetime,
    commute: tuple[float, float] | None = None,
) -> dict[str, Any]:
    reasons = list(reasons)
    discarded = Counter(reason_key(r) for r in reasons if r)
    order = [key for _, key in REASON_KEYS] + ["other"]
    return {
        "criteria": {
            "operation": spec.operation,
            "max_price_eur": spec.max_price_eur,
            "min_bedrooms": spec.min_bedrooms,
            "property_types": spec.property_types,
            "areas": [area.label for area in spec.areas.values()],
            "must_have": spec.must_have.rule,
            "excludes": ["short_term", "room_share"],
            # Work location for "min a pé". Private: lives only in Supabase, behind login.
            "commute": {"lat": commute[0], "lng": commute[1]} if commute else None,
        },
        "counts": {
            "seen": len(reasons),
            "matching": sum(1 for r in reasons if r is None),
            "discarded": {key: discarded[key] for key in order if discarded[key]},
        },
        "updated_at": now.isoformat(),
    }
