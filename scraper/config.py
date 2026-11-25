"""Load and validate config/search.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "search.yaml"

MustHaveRule = Literal["elevator_and_ac", "elevator_or_ac", "ac_plus_elevator_if_above_1st"]


class Area(BaseModel):
    label: str
    municipalities: list[str]
    neighbourhoods: list[str] = Field(default_factory=list)


class MustHave(BaseModel):
    rule: MustHaveRule = "elevator_or_ac"


class Commute(BaseModel):
    address: str | None = None
    mode: str = "driving-car"


class SearchSpec(BaseModel):
    operation: Literal["rent"] = "rent"
    max_price_eur: int
    min_bedrooms: int
    property_types: list[Literal["flat", "house"]]
    areas: dict[str, Area]
    must_have: MustHave = Field(default_factory=MustHave)
    short_term_blocklist: list[str] = Field(default_factory=list)
    room_share_blocklist: list[str] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    commute: Commute = Field(default_factory=Commute)
    stale_after_days: int = 3

    def area_for_municipality(self, municipality: str) -> str | None:
        """Return the area key ("almeria_city", ...) a municipality belongs to."""
        target = _fold(municipality)
        for key, area in self.areas.items():
            if any(_fold(m) == target for m in area.municipalities):
                return key
        return None


def _fold(text: str) -> str:
    """Lowercase and strip Spanish accents for loose comparisons."""
    table = str.maketrans("áéíóúüñ", "aeiouun")
    return text.lower().translate(table).strip()


def load_spec(path: Path = DEFAULT_PATH) -> SearchSpec:
    with path.open(encoding="utf-8") as fh:
        spec = SearchSpec.model_validate(yaml.safe_load(fh))
    # Personal details stay out of the (public) repo: they come from the environment.
    address = os.environ.get("COMMUTE_ADDRESS")
    if address:
        spec.commute.address = address
    return spec
