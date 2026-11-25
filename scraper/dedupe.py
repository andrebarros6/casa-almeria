"""Detect the same flat listed on several portals (or relisted on one)."""

from __future__ import annotations

import math
from collections.abc import Iterable

from scraper.models import Listing

PRICE_TOLERANCE = 0.03
AREA_TOLERANCE = 0.05
MAX_DISTANCE_M = 150.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _close(a: int | None, b: int | None, tol: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol * max(a, b)


def is_duplicate(a: Listing, b: Listing) -> bool:
    if a.id == b.id:
        return False
    if a.bedrooms is None or a.bedrooms != b.bedrooms:
        return False
    if not _close(a.price_eur, b.price_eur, PRICE_TOLERANCE):
        return False
    if not _close(a.area_m2, b.area_m2, AREA_TOLERANCE):
        return False
    if None in (a.lat, a.lng, b.lat, b.lng):
        return False
    assert a.lat is not None and a.lng is not None and b.lat is not None and b.lng is not None
    return haversine_m(a.lat, a.lng, b.lat, b.lng) <= MAX_DISTANCE_M


def assign_group(listing: Listing, candidates: Iterable[Listing]) -> str:
    """Return the group id of the first matching candidate, or the listing's own id."""
    for other in candidates:
        if is_duplicate(listing, other):
            return other.group_id or other.id
    return listing.id


def regroup(active: list[Listing]) -> list[Listing]:
    """Merge listings that sit alone on a card into an older card for the same flat.

    Catches duplicates missed when two sources ran at the same time. Older groups keep
    their id (so shared reactions stay attached); only singletons move. Returns the
    listings whose group_id changed.
    """
    sizes: dict[str, int] = {}
    for item in active:
        key = item.group_id or item.id
        sizes[key] = sizes.get(key, 0) + 1
    ordered = sorted(active, key=lambda x: (x.first_seen is None, x.first_seen or 0, x.id))
    changed: list[Listing] = []
    for i, item in enumerate(ordered):
        own = item.group_id or item.id
        if sizes[own] != 1:
            continue
        for older in ordered[:i]:
            if is_duplicate(item, older):
                target = older.group_id or older.id
                item.group_id = target
                sizes[own] -= 1
                sizes[target] += 1
                changed.append(item)
                break
    return changed
