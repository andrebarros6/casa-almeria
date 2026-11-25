from __future__ import annotations

import httpx
import pytest

from scraper.config import SearchSpec
from scraper.models import Stub
from scraper.sources.enalquiler import (
    EnalquilerSource,
    parse_detail,
    parse_search,
    property_type,
    search_url,
    town_slug,
)

from .conftest import fixture_html

SEARCH = fixture_html("enalquiler/search.html", "latin-1")
DETAIL = fixture_html("enalquiler/detail.html", "latin-1")
AGUADULCE_URL = (
    "https://www.enalquiler.com/alquiler_piso_roquetas-de-mar/"
    "alquiler-piso-ascensor-aguadulce_7052419.html"
)


def _stub() -> Stub:
    return Stub(
        source="enalquiler",
        source_id="7052419",
        url=AGUADULCE_URL,
        price_eur=900,
        title="Alquiler piso ascensor Aguadulce",
        municipality="Roquetas de Mar",
    )


def test_parse_search_all_and_filtered_by_town() -> None:
    every = parse_search(SEARCH)
    assert len(every) == 15
    towns = {"almeria": "Almería", "roquetas-de-mar": "Roquetas de Mar"}
    ours = parse_search(SEARCH, towns)
    assert len(ours) == 12  # 6 piso + 1 atico in Almería, 5 in Roquetas
    assert {s.municipality for s in ours} == {"Almería", "Roquetas de Mar"}
    aguadulce = next(s for s in ours if s.source_id == "7052419")
    assert aguadulce.price_eur == 900
    assert aguadulce.url == AGUADULCE_URL
    assert aguadulce.title == "Alquiler piso ascensor Aguadulce"


def test_parse_search_skips_cards_without_link_or_price() -> None:
    html = '<li class="propertyCard"><span class="propertyCard__price--value">900</span></li>'
    assert parse_search(html) == []


def test_parse_detail(spec: SearchSpec) -> None:
    listing = parse_detail(DETAIL, _stub(), spec)
    assert (listing.bedrooms, listing.bathrooms, listing.area_m2) == (2, 2, 70)
    assert listing.property_type == "flat"
    assert listing.area_key == "west_coast"
    assert listing.lat == pytest.approx(36.8133)
    assert listing.lng == pytest.approx(-2.56617)
    # "Jardín" is crossed out (class="disabled") and must not count
    assert listing.features == {"ac", "elevator", "terrace", "furnished"}
    assert len(listing.photos) == 10
    assert all("/7052419-" in p and p.endswith("_or.jpg") for p in listing.photos)
    assert listing.description.startswith("¡Descubre tu nuevo hogar")


def test_parse_detail_minimal() -> None:
    listing = parse_detail("<html></html>", _stub())
    assert listing.lat is None and listing.photos == [] and listing.area_key is None
    assert listing.bedrooms is None


def test_resume_items_with_dormitorios_and_junk() -> None:
    html = (
        '<li class="resume-list-item">3 Dormitorios</li>'
        '<li class="resume-list-item">Exterior</li>'
        '<li class="resume-list-item">1 Baño</li>'
    )
    listing = parse_detail(html, _stub())
    assert (listing.bedrooms, listing.bathrooms, listing.area_m2) == (3, 1, None)


@pytest.mark.parametrize(
    ("slug", "expected"), [("piso", "flat"), ("atico", "flat"), ("casa", "house"), ("local", None)]
)
def test_property_type(slug: str, expected: str | None) -> None:
    assert property_type(slug) == expected


def test_town_slug_and_url() -> None:
    assert town_slug("Roquetas de Mar") == "roquetas-de-mar"
    assert town_slug("Mojácar") == "mojacar"
    assert search_url() == "https://www.enalquiler.com/search?tipo_base=1&provincia=4"
    assert search_url(2).endswith("&page=2")


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self.pages.get(url, "<html></html>")


def test_source_search_stops_when_pages_repeat_or_empty(spec: SearchSpec) -> None:
    fetcher = FakeFetcher({search_url(1): SEARCH, search_url(2): SEARCH})
    source = EnalquilerSource(fetcher)  # type: ignore[arg-type]
    stubs = source.search(spec)
    assert fetcher.calls == [search_url(1), search_url(2)]
    assert {s.municipality for s in stubs} == {"Almería", "Roquetas de Mar", "Mojácar"}
    assert all(s.source_id for s in stubs)

    empty = FakeFetcher({})
    assert EnalquilerSource(empty).search(spec) == []  # type: ignore[arg-type]
    assert empty.calls == [search_url(1)]

    detail_fetcher = FakeFetcher({AGUADULCE_URL: DETAIL})
    listing = EnalquilerSource(detail_fetcher).fetch_detail(_stub(), spec)  # type: ignore[arg-type]
    assert listing.area_m2 == 70


class StatusFetcher:
    """Serves page 1, then raises the given HTTP status for every other URL."""

    def __init__(self, status: int) -> None:
        self.status = status

    def get(self, url: str) -> str:
        if url == search_url(1):
            return SEARCH
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            "x", request=request, response=httpx.Response(self.status, request=request)
        )


def test_404_after_first_page_ends_pagination(spec: SearchSpec) -> None:
    assert len(EnalquilerSource(StatusFetcher(404)).search(spec)) == 13  # type: ignore[arg-type]


def test_other_http_errors_propagate(spec: SearchSpec) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        EnalquilerSource(StatusFetcher(500)).search(spec)  # type: ignore[arg-type]
