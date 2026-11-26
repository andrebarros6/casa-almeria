"""The normalised listing shape every source adapter produces."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

PropertyType = Literal["flat", "house"]

# Canonical feature keys. Adapters map portal-specific labels onto these.
FEATURES = (
    "elevator",
    "ac",
    "terrace",
    "balcony",
    "parking",
    "pool",
    "furnished",
    "pets",
    "no_pets",
    "heating",
    "storage",
)


class Stub(BaseModel):
    """What a search-results page tells us, before fetching the detail page."""

    source: str
    source_id: str
    url: str
    price_eur: int
    title: str = ""
    municipality: str | None = None
    neighbourhood: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


class PricePoint(BaseModel):
    at: datetime
    price_eur: int


class Listing(BaseModel):
    source: str
    source_id: str
    url: str
    title: str
    description: str = ""
    price_eur: int
    bedrooms: int | None = None
    bathrooms: int | None = None
    area_m2: int | None = None
    floor: int | None = None  # 0 = ground floor; None = unknown
    property_type: PropertyType | None = None
    municipality: str | None = None
    neighbourhood: str | None = None
    area_key: str | None = None
    lat: float | None = None
    lng: float | None = None
    photos: list[str] = Field(default_factory=list)
    features: set[str] = Field(default_factory=set)
    published_at: date | None = None
    is_temporary: bool = False  # portal flags it as a seasonal/temporary rental
    features_known: bool = True  # False for listings from alert emails (no feature data)

    # Pipeline-managed fields
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    gone: bool = False
    group_id: str | None = None
    rejected_reason: str | None = None
    price_history: list[PricePoint] = Field(default_factory=list)
    commute_min: int | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"


class Lead(BaseModel):
    """A card you're pursuing (managed from the page; the scraper only reads it for nudges)."""

    group_id: str
    stage: str
    stage_at: datetime
    next_action_at: datetime | None = None
