from __future__ import annotations

from typing import Any

import pytest

from scraper.browser import BrowserFetcher
from scraper.config import SearchSpec
from scraper.filters import rejection_reason
from scraper.http import SourceBlocked
from scraper.sources.fotocasa import (
    FotocasaSource,
    parse_search,
    search_url,
    to_listing,
    total_count,
    town_slug,
)

from .conftest import fixture_html, make_listing

SEARCH = fixture_html("fotocasa/search.html")

# --- fotocasa parsing -----------------------------------------------------


def test_parse_search(spec: SearchSpec) -> None:
    listings = parse_search(SEARCH, spec)
    assert len(listings) == 7
    assert total_count(SEARCH) == 168
    first = listings[0]
    assert first.source_id == "190865962"
    assert first.url.startswith("https://www.fotocasa.es/es/alquiler/vivienda/")
    assert first.price_eur == 990
    assert first.title == "Piso en Paseo de San Luis, 6, Centro"
    assert first.property_type == "flat"
    assert first.municipality == "Almería" and first.area_key == "almeria_city"
    assert first.neighbourhood == "Centro"
    assert {"ac", "elevator", "furnished"} <= first.features
    assert first.bedrooms and first.bathrooms and first.area_m2
    assert first.lat and first.lng
    assert first.photos and first.published_at is not None
    assert first.floor is None
    assert not first.is_temporary


def test_temporary_rentals_are_flagged_and_rejected(spec: SearchSpec) -> None:
    temporary = [item for item in parse_search(SEARCH, spec) if item.is_temporary]
    assert len(temporary) == 2
    assert all(rejection_reason(item, spec) == "short-term: portal flag" for item in temporary)


def test_not_furnished_overrides(spec: SearchSpec) -> None:
    raw = {
        "id": 1,
        "rawPrice": 700,
        "features": [{"key": "furnished", "value": 19}, {"key": "not_furnished", "value": 130}],
        "buildingType": "House",
        "buildingSubtype": "Chalet",
    }
    listing = to_listing(raw, spec)
    assert "furnished" not in listing.features
    assert listing.property_type == "house"
    assert listing.title == "Chalet en"
    assert listing.published_at is None and listing.area_key is None


def test_unknown_building_type() -> None:
    listing = to_listing({"id": 2, "rawPrice": 1, "buildingType": "Garage"})
    assert listing.property_type is None
    assert listing.title == "Vivienda en"


def test_page_without_props() -> None:
    assert parse_search("<html></html>") == []
    assert total_count("<html></html>") == 0


def test_urls(spec: SearchSpec) -> None:
    assert town_slug("Almería") == "almeria-capital"
    assert town_slug("Roquetas de Mar") == "roquetas-de-mar"
    assert search_url("Almería", spec) == (
        "https://www.fotocasa.es/es/alquiler/viviendas/almeria-capital/todas-las-zonas/l"
        "?maxPrice=1000&minRooms=2"
    )
    assert "/l/3?maxPrice" in search_url("Vera", spec, 3)


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []
        self.closed = False

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self.pages.get(url, "<html></html>")

    def close(self) -> None:
        self.closed = True


def test_source_paginates_by_count_and_returns_cached_details(spec: SearchSpec) -> None:
    spec.areas = {"almeria_city": spec.areas["almeria_city"]}
    fetcher = FakeFetcher({search_url("Almería", spec, n): SEARCH for n in range(1, 7)})
    source = FotocasaSource(fetcher)  # type: ignore[arg-type]
    stubs = source.search(spec)
    # 168 results / 30 per page = 6 pages
    assert len(fetcher.calls) == 6
    assert fetcher.closed
    assert len(stubs) == 7
    detail = source.fetch_detail(stubs[0].model_copy(update={"price_eur": 950}), spec)
    assert detail.price_eur == 950
    assert detail.features  # came from the search JSON, no extra request
    assert len(fetcher.calls) == 6


def test_temporary_flag_filter_runs_before_blocklist(spec: SearchSpec) -> None:
    listing = make_listing(is_temporary=True, description="alquiler de temporada")
    assert rejection_reason(listing, spec) == "short-term: portal flag"


# --- BrowserFetcher -------------------------------------------------------


class FakeMouse:
    def __init__(self) -> None:
        self.scrolls = 0

    def wheel(self, delta_x: float, delta_y: float) -> None:
        self.scrolls += 1


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakePage:
    def __init__(self, html: str, status: int = 200) -> None:
        self.html, self.status = html, status
        self.mouse = FakeMouse()
        self.visited: list[str] = []

    def goto(self, url: str, *, timeout: Any = None, wait_until: Any = None) -> FakeResponse:
        self.visited.append(url)
        return FakeResponse(self.status)

    def content(self) -> str:
        return self.html


def _browser(page: FakePage, closed: list[bool], sleeps: list[float]) -> BrowserFetcher:
    return BrowserFetcher(
        page_factory=lambda: (page, lambda: closed.append(True)), sleep=sleeps.append
    )


def test_browser_fetcher_reuses_page_waits_and_scrolls() -> None:
    page, closed, sleeps = FakePage("<html>ok</html>"), [], []  # type: ignore[var-annotated]
    fetcher = _browser(page, closed, sleeps)
    assert fetcher.get("https://a.test/1") == "<html>ok</html>"
    assert fetcher.get("https://a.test/2") == "<html>ok</html>"
    assert page.visited == ["https://a.test/1", "https://a.test/2"]
    assert page.mouse.scrolls >= 4
    assert any(s >= 6 for s in sleeps)  # pause between pages
    fetcher.close()
    assert closed == [True]
    fetcher.close()  # closing twice is harmless
    assert closed == [True]


@pytest.mark.parametrize(
    ("html", "status"),
    [
        ("<html>ok</html>", 403),
        ('<script src="https://geo.captcha-delivery.com/c.js"></script>', 200),
        ("<title>Pardon Our Interruption</title>", 200),
    ],
)
def test_browser_fetcher_detects_blocks(html: str, status: int) -> None:
    fetcher = _browser(FakePage(html, status), [], [])
    with pytest.raises(SourceBlocked):
        fetcher.get("https://a.test/")
