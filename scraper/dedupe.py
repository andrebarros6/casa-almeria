"""Detect the same flat listed on several portals (or relisted on one)."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from scraper.models import Listing

PRICE_TOLERANCE = 0.03
AREA_TOLERANCE = 0.05
MAX_DISTANCE_M = 150.0
# Portals geocode the same flat up to km apart, so near-identical text also counts.
# 0.9, not lower: agencies reuse ~65%-identical templates for *different* flats.
DESCRIPTION_SIMILARITY = 0.9
MIN_DESCRIPTION_WORDS = 15


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


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return set(re.sub(r"\W+", " ", folded).split())


def description_similarity(a: Listing, b: Listing) -> float:
    """Word-set overlap (Jaccard); 0 when either description is too short to judge."""
    wa, wb = _words(a.description), _words(b.description)
    if len(wa) < MIN_DESCRIPTION_WORDS or len(wb) < MIN_DESCRIPTION_WORDS:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _near(a: Listing, b: Listing) -> bool:
    if a.lat is None or a.lng is None or b.lat is None or b.lng is None:
        return False
    return haversine_m(a.lat, a.lng, b.lat, b.lng) <= MAX_DISTANCE_M


def is_duplicate(a: Listing, b: Listing) -> bool:
    if a.id == b.id:
        return False
    if a.bedrooms is None or a.bedrooms != b.bedrooms:
        return False
    if not _close(a.price_eur, b.price_eur, PRICE_TOLERANCE):
        return False
    if not _close(a.area_m2, b.area_m2, AREA_TOLERANCE):
        return False
    return _near(a, b) or description_similarity(a, b) >= DESCRIPTION_SIMILARITY


def assign_group(listing: Listing, candidates: Iterable[Listing]) -> str:
    """Return the group id of the first matching candidate, or the listing's own id."""
    for other in candidates:
        if is_duplicate(listing, other):
            return other.group_id or other.id
    return listing.id


@dataclass
class Regrouping:
    changed: list[Listing] = field(default_factory=list)  # listings whose group_id moved
    moves: dict[str, str] = field(default_factory=dict)  # absorbed group id -> surviving id


def regroup(active: list[Listing]) -> Regrouping:
    """Merge cards (groups) that are the same flat.

    Catches duplicates missed when sources ran at the same time or when two multi-listing
    cards match each other. The surviving card is the oldest one, so its id (and the
    reactions keyed on it) is stable; `moves` tells the caller which reactions to move.
    """
    gid = {item.id: item.group_id or item.id for item in active}
    parent: dict[str, str] = {g: g for g in gid.values()}

    def find(g: str) -> str:
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            ga, gb = find(gid[a.id]), find(gid[b.id])
            if ga != gb and is_duplicate(a, b):
                parent[ga] = gb

    # Survivor per merged set: the group first seen earliest (ties: smallest id).
    oldest: dict[str, tuple[bool, datetime | None, str]] = {}
    for item in active:
        g = gid[item.id]
        key = (item.first_seen is None, item.first_seen, g)
        root = find(g)
        current = oldest.get(root)
        if current is None or _before(key, current):
            oldest[root] = key
    survivor = {root: key[2] for root, key in oldest.items()}

    result = Regrouping()
    for item in active:
        old = gid[item.id]
        new = survivor[find(old)]
        if new != old:
            result.moves[old] = new
            item.group_id = new
            result.changed.append(item)
    return result


def _before(a: tuple[bool, datetime | None, str], b: tuple[bool, datetime | None, str]) -> bool:
    if a[0] != b[0]:
        return not a[0]  # known first_seen beats unknown
    if a[1] is not None and b[1] is not None and a[1] != b[1]:
        return a[1] < b[1]
    return a[2] < b[2]
