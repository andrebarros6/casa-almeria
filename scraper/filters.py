"""Hard filters from the search spec. Returns a rejection reason, or None if the listing passes."""

from __future__ import annotations

import re
import unicodedata

from scraper.config import SearchSpec
from scraper.models import Listing


def _fold(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


def phrase_hit(listing: Listing, phrases: list[str]) -> str | None:
    haystack = _fold(f"{listing.title} {listing.description}")
    for phrase in phrases:
        if _fold(phrase) in haystack:
            return phrase
    return None


def must_have_ok(listing: Listing, spec: SearchSpec) -> bool:
    f = listing.features
    has_lift, has_ac = "elevator" in f, "ac" in f
    if listing.property_type == "house":
        return has_ac
    rule = spec.must_have.rule
    if rule == "elevator_and_ac":
        return has_lift and has_ac
    if rule == "elevator_or_ac":
        return has_lift or has_ac
    # ac_plus_elevator_if_above_1st: unknown floor is given the benefit of the doubt.
    needs_lift = listing.floor is not None and listing.floor >= 2
    return has_ac and (has_lift or not needs_lift)


def rejection_reason(listing: Listing, spec: SearchSpec) -> str | None:
    if listing.price_eur > spec.max_price_eur:
        return f"price {listing.price_eur} > {spec.max_price_eur}"
    if listing.bedrooms is not None and listing.bedrooms < spec.min_bedrooms:
        return f"bedrooms {listing.bedrooms} < {spec.min_bedrooms}"
    if listing.property_type is not None and listing.property_type not in spec.property_types:
        return f"type {listing.property_type}"
    if listing.is_temporary:
        return "short-term: portal flag"
    hit = phrase_hit(listing, spec.short_term_blocklist)
    if hit:
        return f"short-term: '{hit}'"
    hit = phrase_hit(listing, spec.room_share_blocklist)
    if hit:
        return f"room share: '{hit}'"
    if listing.features_known and not must_have_ok(listing, spec):
        return f"must-have ({spec.must_have.rule})"
    return None
