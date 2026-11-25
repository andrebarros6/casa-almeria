"""pisos.com adapter (plain HTTP, runs on GitHub Actions)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from scraper.config import SearchSpec
from scraper.http import Fetcher
from scraper.models import Listing, PropertyType, Stub

BASE = "https://www.pisos.com"
MAX_PAGES = 10

SLUG_OVERRIDES = {"almeria": "almeria_capital"}

FLAT_WORDS = ("piso", "atico", "duplex", "estudio", "apartamento", "loft", "planta baja")
HOUSE_WORDS = ("casa", "chalet", "adosado", "pareado", "villa", "cortijo", "finca", "bungalow")

# Folded feature label prefix -> canonical feature key. Order matters (negatives first).
FEATURE_LABELS: list[tuple[str, str | None]] = [
    ("no se aceptan mascotas", "no_pets"),
    ("se aceptan mascotas", "pets"),
    ("mascotas", "pets"),
    ("sin amueblar", None),
    ("no amueblado", None),
    ("amueblado", "furnished"),
    ("ascensor", "elevator"),
    ("aire acondicionado", "ac"),
    ("terraza", "terrace"),
    ("balcon", "balcony"),
    ("garaje", "parking"),
    ("plaza de garaje", "parking"),
    ("parking", "parking"),
    ("piscina", "pool"),
    ("calefaccion", "heating"),
    ("trastero", "storage"),
]


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def municipality_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", fold(name)).strip("_")
    return SLUG_OVERRIDES.get(slug, slug)


def search_url(municipality: str, spec: SearchSpec, page: int = 1) -> str:
    url = (
        f"{BASE}/alquiler/viviendas-{municipality_slug(municipality)}/"
        f"hasta-{spec.max_price_eur}/desde-{spec.min_bedrooms}-habitaciones/"
    )
    return url if page == 1 else f"{url}{page}/"


def _int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text.split(",")[0])
    return int(digits) if digits else None


def _text(node: Node | None) -> str:
    return node.text(strip=True) if node is not None else ""


def parse_search(html: str, municipality: str | None = None) -> list[Stub]:
    tree = HTMLParser(html)
    stubs: list[Stub] = []
    for card in tree.css("div.ad-preview"):
        source_id = card.attributes.get("id")
        href = card.attributes.get("data-lnk-href")
        price = _int(_text(card.css_first(".ad-preview__price")))
        if not source_id or not href or price is None:
            continue
        subtitle = _text(card.css_first(".ad-preview__subtitle"))
        neighbourhood = subtitle.split("(")[0].strip() or None
        stubs.append(
            Stub(
                source="pisos",
                source_id=source_id,
                url=urljoin(BASE, href),
                price_eur=price,
                title=_text(card.css_first(".ad-preview__title")),
                municipality=municipality,
                neighbourhood=neighbourhood,
            )
        )
    return stubs


def property_type_from_title(title: str) -> PropertyType | None:
    first = fold(title)
    if first.startswith(HOUSE_WORDS):
        return "house"
    if first.startswith(FLAT_WORDS):
        return "flat"
    return None


def _features(tree: HTMLParser) -> tuple[set[str], dict[str, str]]:
    """Return (canonical feature keys, raw label->value pairs)."""
    keys: set[str] = set()
    values: dict[str, str] = {}
    for feat in tree.css(".features__feature"):
        label = fold(_text(feat.css_first(".features__label")).rstrip(":").strip())
        value = _text(feat.css_first(".features__value"))
        if not label:
            continue
        values[label] = value
        if fold(value) in ("no", "0"):
            continue
        for prefix, key in FEATURE_LABELS:
            if label.startswith(prefix):
                if key:
                    keys.add(key)
                break
    if "no_pets" in keys:
        keys.discard("pets")
    return keys, values


def _floor(value: str | None) -> int | None:
    if not value:
        return None
    v = fold(value)
    if v.startswith(("bajo", "planta baja", "entreplanta", "semisotano", "sotano")):
        return 0
    return _int(v)


def parse_detail(html: str, stub: Stub, spec: SearchSpec | None = None) -> Listing:
    tree = HTMLParser(html)
    features, values = _features(tree)
    title = _text(tree.css_first("h1")) or stub.title

    lat = lng = None
    geo = re.search(r"latitude=(-?[\d.]+)&(?:amp;)?longitude=(-?[\d.]+)", html)
    if geo:
        lat, lng = float(geo.group(1)), float(geo.group(2))

    # The same photo appears in several sizes (xl/fch/fchm); keep each once, gallery size.
    photos: list[str] = []
    for key in re.findall(r"https://fotos\.imghs\.net/(?:xl|fch|fchm)-wp/([^\"'\s]+?\.jpg)", html):
        url = f"https://fotos.imghs.net/fchm-wp/{key}"
        if url not in photos:
            photos.append(url)

    published = None
    pub = re.search(r'fechaPrimeraPublicacion&quot;:&quot;|fechaPrimeraPublicacion":"', html)
    if pub:
        raw = html[pub.end() : pub.end() + 10]
        try:
            published = datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError:
            published = None

    municipality = stub.municipality
    return Listing(
        source=stub.source,
        source_id=stub.source_id,
        url=stub.url,
        title=title,
        description=_text(tree.css_first(".description__content")),
        price_eur=stub.price_eur,
        bedrooms=_int(values.get("habitaciones")),
        bathrooms=_int(values.get("banos")),
        area_m2=_int(values.get("superficie construida") or values.get("superficie util")),
        floor=_floor(values.get("planta")),
        property_type=property_type_from_title(stub.title or title),
        municipality=municipality,
        neighbourhood=stub.neighbourhood,
        area_key=spec.area_for_municipality(municipality) if spec and municipality else None,
        lat=lat,
        lng=lng,
        photos=photos[:15],
        features=features,
        published_at=published if isinstance(published, date) else None,
    )


class PisosSource:
    name = "pisos"
    runs_on = "cloud"

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher()

    def search(self, spec: SearchSpec) -> list[Stub]:
        seen: dict[str, Stub] = {}
        for area in spec.areas.values():
            for municipality in area.municipalities:
                for page in range(1, MAX_PAGES + 1):
                    stubs = parse_search(
                        self.fetcher.get(search_url(municipality, spec, page)), municipality
                    )
                    new = [s for s in stubs if s.source_id not in seen]
                    for s in new:
                        seen[s.source_id] = s
                    if not new:  # past the last page, pisos.com repeats the final page
                        break
        return list(seen.values())

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        return parse_detail(self.fetcher.get(stub.url), stub, spec)
