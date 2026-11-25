from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scraper.config import SearchSpec, load_spec
from scraper.models import Listing

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / name).read_text(encoding=encoding)


@pytest.fixture
def spec() -> SearchSpec:
    return load_spec()


def make_listing(**overrides: Any) -> Listing:
    data: dict[str, Any] = {
        "source": "pisos",
        "source_id": "1",
        "url": "https://example.test/1",
        "title": "Piso en calle Real",
        "description": "Bonito piso",
        "price_eur": 800,
        "bedrooms": 2,
        "area_m2": 80,
        "property_type": "flat",
        "lat": 36.84,
        "lng": -2.46,
        "features": {"elevator"},
    }
    data.update(overrides)
    return Listing(**data)
