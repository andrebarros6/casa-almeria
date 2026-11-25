from __future__ import annotations

import pytest

from scraper.config import SearchSpec
from scraper.models import Stub
from scraper.sources.pisos import (
    PisosSource,
    _floor,
    municipality_slug,
    parse_detail,
    parse_search,
    property_type_from_title,
    search_url,
)

from .conftest import fixture_html


def _stub(**kw: object) -> Stub:
    data: dict[str, object] = {
        "source": "pisos",
        "source_id": "66740846772.106100",
        "url": "https://www.pisos.com/alquilar/x/",
        "price_eur": 950,
        "title": "Piso en calle Zagal",
        "municipality": "Almería",
        "neighbourhood": "Plaza de Toros-Santa Rita",
    }
    data.update(kw)
    return Stub.model_validate(data)


def test_parse_search_reads_all_cards() -> None:
    stubs = parse_search(fixture_html("pisos/search.html"), "Almería")
    assert len(stubs) == 30
    first = stubs[0]
    assert first.id.startswith("pisos:")
    assert first.url.startswith("https://www.pisos.com/alquilar/")
    assert 0 < first.price_eur <= 1000
    assert first.title
    assert first.municipality == "Almería"
    assert all(s.price_eur > 0 for s in stubs)
    assert len({s.source_id for s in stubs}) == 30


def test_parse_search_skips_incomplete_cards() -> None:
    html = '<div class="ad-preview" id="1"><span class="ad-preview__price">x</span></div>'
    assert parse_search(html) == []


def test_parse_detail_basic(spec: SearchSpec) -> None:
    listing = parse_detail(fixture_html("pisos/detail.html"), _stub(), spec)
    assert listing.title == "Piso en alquiler en Calle Zagal"
    assert (listing.bedrooms, listing.bathrooms, listing.area_m2, listing.floor) == (3, 3, 142, 2)
    assert listing.property_type == "flat"
    assert listing.area_key == "almeria_city"
    assert listing.lat == pytest.approx(36.8455)
    assert listing.lng == pytest.approx(-2.4588)
    assert {"ac", "elevator", "balcony"} <= listing.features
    assert listing.published_at is not None and listing.published_at.isoformat() == "2026-08-14"
    assert listing.description.startswith("Descubre")
    assert listing.photos and all("fotos.imghs.net/fchm-wp/" in p for p in listing.photos)
    assert len(listing.photos) == len(set(listing.photos))


def test_parse_detail_valued_features(spec: SearchSpec) -> None:
    listing = parse_detail(fixture_html("pisos/detail_pool_ac.html"), _stub(), spec)
    assert {"ac", "pool", "parking", "furnished", "terrace"} <= listing.features
    assert len(listing.photos) > 5
    assert "septiembre a junio" in listing.description


def test_parse_detail_no_pets(spec: SearchSpec) -> None:
    listing = parse_detail(fixture_html("pisos/detail_no_pets.html"), _stub(), spec)
    assert "no_pets" in listing.features
    assert "pets" not in listing.features
    assert listing.floor == 7


def test_parse_detail_without_spec_has_no_area() -> None:
    listing = parse_detail(fixture_html("pisos/detail.html"), _stub())
    assert listing.area_key is None


def test_parse_detail_minimal_html_uses_stub_title() -> None:
    listing = parse_detail("<html></html>", _stub(title="Chalet en la playa"))
    assert listing.title == "Chalet en la playa"
    assert listing.property_type == "house"
    assert listing.lat is None and listing.published_at is None and listing.features == set()


def test_parse_detail_bad_date_is_ignored() -> None:
    html = '<span data-var=\'{"fechaPrimeraPublicacion":"99/99/2026"}\'></span>'
    assert parse_detail(html, _stub()).published_at is None


def test_negative_feature_values_are_ignored() -> None:
    html = (
        '<div class="features__feature"><span class="features__label">Ascensor: </span>'
        '<span class="features__value">No</span></div>'
        '<div class="features__feature"><span class="features__label">Sin amueblar</span></div>'
        '<div class="features__feature"><span class="features__label">Trastero</span></div>'
        '<div class="features__feature"><span class="features__label"></span></div>'
    )
    assert parse_detail(html, _stub()).features == {"storage"}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Piso en calle X", "flat"),
        ("Ático en Zapillo", "flat"),
        ("Dúplex en Aguadulce", "flat"),
        ("Casa adosada en Vera", "house"),
        ("Chalet en Mojácar", "house"),
        ("Local comercial", None),
    ],
)
def test_property_type_from_title(title: str, expected: str | None) -> None:
    assert property_type_from_title(title) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2ª", 2), ("Bajo", 0), ("Entreplanta", 0), ("11ª", 11), (None, None), ("", None)],
)
def test_floor(value: str | None, expected: int | None) -> None:
    assert _floor(value) == expected


def test_slugs_and_urls(spec: SearchSpec) -> None:
    assert municipality_slug("Almería") == "almeria_capital"
    assert municipality_slug("Roquetas de Mar") == "roquetas_de_mar"
    assert municipality_slug("Níjar") == "nijar"
    assert search_url("Vera", spec) == (
        "https://www.pisos.com/alquiler/viviendas-vera/hasta-1000/desde-2-habitaciones/"
    )
    assert search_url("Vera", spec, 3).endswith("/desde-2-habitaciones/3/")


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self.pages.get(url, "<html></html>")


def test_source_search_paginates_and_stops_on_repeat(spec: SearchSpec) -> None:
    page = fixture_html("pisos/search.html")
    spec.areas = {"almeria_city": spec.areas["almeria_city"]}
    url1 = search_url("Almería", spec)
    fetcher = FakeFetcher({url1: page, search_url("Almería", spec, 2): page})
    source = PisosSource(fetcher)  # type: ignore[arg-type]
    stubs = source.search(spec)
    assert len(stubs) == 30
    assert fetcher.calls == [url1, search_url("Almería", spec, 2)]  # page 2 repeated -> stop
    listing = source.fetch_detail(stubs[0], spec)
    assert listing.source_id == stubs[0].source_id
