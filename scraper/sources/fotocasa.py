"""Fotocasa adapter (real Chrome on the owner's PC).

The search page embeds every listing's full data as JSON (<script id="__initial_props__">),
so there's no need to open detail pages: fetch_detail returns what search already parsed.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from scraper.browser import BrowserFetcher
from scraper.config import SearchSpec
from scraper.models import Listing, PropertyType, Stub

BASE = "https://www.fotocasa.es"
PAGE_SIZE = 30
MAX_PAGES = 15
SLUG_OVERRIDES = {"almeria": "almeria-capital"}
PROPS_RE = re.compile(r'<script[^>]*id="__initial_props__"[^>]*>(.*?)</script>', re.S)

FEATURES = {
    "elevator": "elevator",
    "air_conditioner": "ac",
    "terrace": "terrace",
    "balcony": "balcony",
    "parking": "parking",
    "community_pool": "pool",
    "private_pool": "pool",
    "furnished": "furnished",
    "heating": "heating",
    "storage_room": "storage",
    "pets": "pets",
    "pets_allowed": "pets",
}
SUBTYPE_LABEL = {
    "Flat": "Piso",
    "Attic": "Ático",
    "Apartment": "Apartamento",
    "Duplex": "Dúplex",
    "Studio": "Estudio",
    "Loft": "Loft",
    "House": "Casa",
    "Chalet": "Chalet",
    "Townhouse": "Casa adosada",
    "SemidetachedHouse": "Casa pareada",
    "Villa": "Villa",
}
HOUSE_TYPES = {"House", "Chalet", "Townhouse", "SemidetachedHouse", "Villa", "Rustic"}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def town_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")
    return SLUG_OVERRIDES.get(slug, slug)


def search_url(municipality: str, spec: SearchSpec, page: int = 1) -> str:
    path = f"{BASE}/es/alquiler/viviendas/{town_slug(municipality)}/todas-las-zonas/l"
    if page > 1:
        path += f"/{page}"
    return f"{path}?maxPrice={spec.max_price_eur}&minRooms={spec.min_bedrooms}"


def _props(html: str) -> dict[str, Any]:
    match = PROPS_RE.search(html)
    if not match:
        return {}
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def total_count(html: str) -> int:
    result = _props(html).get("initialSearch", {}).get("result", {})
    return int(result.get("count") or 0)


def _property_type(building_type: str, subtype: str) -> PropertyType | None:
    if building_type in HOUSE_TYPES or subtype in HOUSE_TYPES:
        return "house"
    if building_type == "Flat":
        return "flat"
    return None


def to_listing(raw: dict[str, Any], spec: SearchSpec | None = None) -> Listing:
    values = {f["key"]: f.get("value") for f in raw.get("features", [])}
    features = {FEATURES[k] for k in values if k in FEATURES}
    if "not_furnished" in values:
        features.discard("furnished")

    address = raw.get("address") or {}
    coords = raw.get("coordinates") or {}
    municipality = address.get("municipality")
    subtype = raw.get("buildingSubtype") or ""
    label = SUBTYPE_LABEL.get(subtype, "Vivienda")
    location = raw.get("location") or address.get("district") or municipality or ""

    published = None
    stamp = (raw.get("dateOriginal") or {}).get("timestamp")
    if stamp:
        published = datetime.fromtimestamp(stamp / 1000, tz=UTC).date()

    detail = raw.get("detail") or {}
    return Listing(
        source="fotocasa",
        source_id=str(raw["id"]),
        url=BASE + str(detail.get("es-ES", "")),
        title=f"{label} en {location}".strip(),
        description=raw.get("description") or "",
        price_eur=int(raw.get("rawPrice") or 0),
        bedrooms=values.get("rooms"),
        bathrooms=values.get("bathrooms"),
        area_m2=values.get("surface"),
        floor=None,  # Fotocasa's floor value is an internal id, not a floor number
        property_type=_property_type(raw.get("buildingType") or "", subtype),
        municipality=municipality,
        neighbourhood=address.get("neighborhood") or address.get("district"),
        area_key=spec.area_for_municipality(municipality) if spec and municipality else None,
        lat=coords.get("latitude"),
        lng=coords.get("longitude"),
        photos=[m["src"] for m in raw.get("multimedia", []) if m.get("type") == "image"][:15],
        features=features,
        published_at=published,
        is_temporary=bool(raw.get("isTemporaryRental")),
    )


def parse_search(html: str, spec: SearchSpec | None = None) -> list[Listing]:
    result = _props(html).get("initialSearch", {}).get("result", {})
    return [to_listing(raw, spec) for raw in result.get("realEstates", [])]


class FotocasaSource:
    name = "fotocasa"
    runs_on = "local"
    free_details = True  # search JSON already has everything

    def __init__(self, fetcher: BrowserFetcher | None = None) -> None:
        self.fetcher = fetcher or BrowserFetcher()
        self._parsed: dict[str, Listing] = {}

    def search(self, spec: SearchSpec) -> list[Stub]:
        self._parsed = {}
        try:
            for area in spec.areas.values():
                for municipality in area.municipalities:
                    self._search_town(municipality, spec)
        finally:
            self.fetcher.close()
        return [
            Stub(
                source=self.name,
                source_id=item.source_id,
                url=item.url,
                price_eur=item.price_eur,
                title=item.title,
                municipality=item.municipality,
                neighbourhood=item.neighbourhood,
            )
            for item in self._parsed.values()
        ]

    def _search_town(self, municipality: str, spec: SearchSpec) -> None:
        html = self.fetcher.get(search_url(municipality, spec))
        pages = min(MAX_PAGES, -(-total_count(html) // PAGE_SIZE))
        for page in range(1, pages + 1):
            if page > 1:
                html = self.fetcher.get(search_url(municipality, spec, page))
            for listing in parse_search(html, spec):
                self._parsed.setdefault(listing.source_id, listing)

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        listing = self._parsed[stub.source_id].model_copy(deep=True)
        listing.price_eur = stub.price_eur
        return listing
