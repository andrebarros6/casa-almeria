"""enalquiler.com adapter (plain HTTP, runs on GitHub Actions).

The site has no per-town search URL, so we page through the whole province
(provincia=4, ~350 rentals) and keep only listings in the spec's towns. The town
and property type come from the listing URL: /alquiler_<type>_<town-slug>/...
"""

from __future__ import annotations

import re
import unicodedata

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from scraper.config import SearchSpec
from scraper.http import Fetcher
from scraper.models import Listing, PropertyType, Stub

BASE = "https://www.enalquiler.com"
PROVINCE_ALMERIA = 4
MAX_PAGES = 40

URL_RE = re.compile(r"/alquiler_([a-z]+)_([a-z0-9-]+)/.*_(\d+)\.html")
FLAT_TYPES = {"piso", "atico", "duplex", "estudio", "apartamento", "loft"}
HOUSE_TYPES = {"casa", "chalet", "adosado", "pareado", "villa", "cortijo", "finca", "bungalow"}

FEATURE_LABELS: dict[str, str] = {
    "ascensor": "elevator",
    "aire acondicionado": "ac",
    "terraza": "terrace",
    "balcon": "balcony",
    "parking": "parking",
    "garaje": "parking",
    "plaza de garaje": "parking",
    "piscina": "pool",
    "piscina comunitaria": "pool",
    "amueblado": "furnished",
    "se admiten mascotas": "pets",
    "admite mascotas": "pets",
    "mascotas": "pets",
    "calefaccion": "heating",
    "trastero": "storage",
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def town_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")


def search_url(page: int = 1) -> str:
    url = f"{BASE}/search?tipo_base=1&provincia={PROVINCE_ALMERIA}"
    return url if page == 1 else f"{url}&page={page}"


def _text(node: Node | None) -> str:
    return node.text(strip=True) if node is not None else ""


def _int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def property_type(type_slug: str) -> PropertyType | None:
    if type_slug in FLAT_TYPES:
        return "flat"
    if type_slug in HOUSE_TYPES:
        return "house"
    return None


def parse_search(html: str, towns: dict[str, str] | None = None) -> list[Stub]:
    """towns maps URL slug -> municipality name; None keeps every town."""
    stubs: list[Stub] = []
    for card in HTMLParser(html).css("li.propertyCard"):
        link = card.css_first("a.propertyCard__description--title")
        href = link.attributes.get("href") if link is not None else None
        price = _int(_text(card.css_first(".propertyCard__price--value")))
        match = URL_RE.search(href or "")
        if not href or not match or price is None:
            continue
        slug = match.group(2)
        if towns is not None and slug not in towns:
            continue
        stubs.append(
            Stub(
                source="enalquiler",
                source_id=match.group(3),
                url=href,
                price_eur=price,
                title=_text(link),
                municipality=towns[slug] if towns else slug,
            )
        )
    return stubs


def parse_detail(html: str, stub: Stub, spec: SearchSpec | None = None) -> Listing:
    tree = HTMLParser(html)
    features: set[str] = set()
    for item in tree.css(".property-characteristics-block-list li"):
        if "disabled" in (item.attributes.get("class") or ""):
            continue
        key = FEATURE_LABELS.get(fold(item.text(strip=True)))
        if key:
            features.add(key)

    lat = lng = None
    lat_m = re.search(r"latitude[\"']?\s*[:=]\s*[\"']?(-?\d+\.\d+)", html)
    lng_m = re.search(r"longitude[\"']?\s*[:=]\s*[\"']?(-?\d+\.\d+)", html)
    if lat_m and lng_m:
        lat, lng = round(float(lat_m.group(1)), 6), round(float(lng_m.group(1)), 6)

    # Photo URLs are /viviendas/<pid[:3]>/<pid[3:6]>/<listing>-<pid>_<size>.jpg. The page also
    # shows similar listings, so keep only this listing's photo ids.
    photos: list[str] = []
    for pid in re.findall(rf"\b{re.escape(stub.source_id)}-(\d{{6,}})_", html):
        url = f"https://images.enalquiler.com/viviendas/{pid[:3]}/{pid[3:6]}/{stub.source_id}-{pid}_or.jpg"
        if url not in photos:
            photos.append(url)

    match = URL_RE.search(stub.url)
    type_slug = match.group(1) if match else ""
    details = _resume_details(tree)
    description = _text(tree.css_first("#description"))
    municipality = stub.municipality
    return Listing(
        source=stub.source,
        source_id=stub.source_id,
        url=stub.url,
        title=stub.title,
        description=description,
        price_eur=stub.price_eur,
        bedrooms=details.get("hab"),
        bathrooms=details.get("ban"),
        area_m2=details.get("m2"),
        property_type=property_type(type_slug),
        municipality=municipality,
        area_key=spec.area_for_municipality(municipality) if spec and municipality else None,
        lat=lat,
        lng=lng,
        photos=photos[:15],
        features=features,
    )


def _resume_details(tree: HTMLParser) -> dict[str, int]:
    """Bedrooms / bathrooms / m² from the summary list ('70 m2', '2 Hab', '2 Baños')."""
    out: dict[str, int] = {}
    for item in tree.css("li.resume-list-item"):
        text = fold(item.text(strip=True))
        m = re.match(r"(\d+)\s*(.*)", text)
        if not m:
            continue
        value, unit = int(m.group(1)), m.group(2)
        if unit.startswith("m"):
            out["m2"] = value
        elif unit.startswith(("hab", "dorm")):
            out["hab"] = value
        elif unit.startswith("ban"):
            out["ban"] = value
    return out


class EnalquilerSource:
    name = "enalquiler"
    runs_on = "cloud"

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    def search(self, spec: SearchSpec) -> list[Stub]:
        towns = {
            town_slug(m): m
            for area in spec.areas.values()
            for m in [*area.municipalities, *area.neighbourhoods]
        }
        seen: dict[str, Stub] = {}
        for page in range(1, MAX_PAGES + 1):
            try:
                html = self.fetcher.get(search_url(page))
            except httpx.HTTPStatusError as exc:
                if page > 1 and exc.response.status_code == 404:  # past the last page
                    break
                raise
            page_ids = {s.source_id for s in parse_search(html)}
            if not page_ids or page_ids <= seen.keys():
                break
            for stub in parse_search(html, towns):
                seen.setdefault(stub.source_id, stub)
            for sid in page_ids:
                seen.setdefault(sid, _SKIP)
        return [s for s in seen.values() if s is not _SKIP]

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        return parse_detail(self.fetcher.get(stub.url), stub, spec)


# Placeholder for out-of-area ids, so pagination can tell when pages start repeating.
_SKIP = Stub(source="enalquiler", source_id="", url="", price_eur=0)
