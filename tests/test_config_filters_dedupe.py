from __future__ import annotations

import pytest

from scraper.config import SearchSpec
from scraper.dedupe import assign_group, haversine_m, is_duplicate
from scraper.filters import rejection_reason

from .conftest import make_listing

# --- config ---------------------------------------------------------------


def test_spec_loads_with_expected_criteria(spec: SearchSpec) -> None:
    assert spec.max_price_eur == 1000
    assert spec.min_bedrooms == 2
    assert spec.must_have.rule == "elevator_or_ac"
    assert set(spec.areas) == {"almeria_city", "west_coast", "east_coast"}


@pytest.mark.parametrize(
    ("municipality", "area"),
    [
        ("Almería", "almeria_city"),
        ("ALMERIA", "almeria_city"),
        ("Roquetas de Mar", "west_coast"),
        ("Mojacar", "east_coast"),
        ("Níjar", "east_coast"),
        ("Granada", None),
    ],
)
def test_area_for_municipality(spec: SearchSpec, municipality: str, area: str | None) -> None:
    assert spec.area_for_municipality(municipality) == area


# --- filters --------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, None),
        ({"price_eur": 1000}, None),
        ({"price_eur": 1001}, "price"),
        ({"bedrooms": 1}, "bedrooms"),
        ({"bedrooms": None}, None),
        ({"description": "Alquiler de TEMPORADA hasta junio"}, "short-term"),
        ({"description": "Disponible de septiembre a junio"}, "short-term"),
        ({"title": "Piso vacacional"}, "short-term"),
        ({"description": "Ideal curso escolar"}, "short-term"),
        ({"features": {"ac"}}, None),
        ({"features": {"terrace"}}, "must-have"),
        ({"features": set()}, "must-have"),
        ({"property_type": "house", "features": {"elevator"}}, "must-have"),
        ({"property_type": "house", "features": {"ac"}}, None),
    ],
)
def test_rejection_reason_default_rule(
    spec: SearchSpec, overrides: dict[str, object], expected: str | None
) -> None:
    reason = rejection_reason(make_listing(**overrides), spec)
    if expected is None:
        assert reason is None
    else:
        assert reason is not None and reason.startswith(expected)


def test_property_type_outside_spec_is_rejected(spec: SearchSpec) -> None:
    spec.property_types = ["flat"]
    assert rejection_reason(make_listing(property_type="house", features={"ac"}), spec) == (
        "type house"
    )


@pytest.mark.parametrize(
    ("rule", "features", "floor", "ok"),
    [
        ("elevator_and_ac", {"elevator", "ac"}, 3, True),
        ("elevator_and_ac", {"ac"}, 3, False),
        ("ac_plus_elevator_if_above_1st", {"ac"}, 1, True),
        ("ac_plus_elevator_if_above_1st", {"ac"}, 2, False),
        ("ac_plus_elevator_if_above_1st", {"ac", "elevator"}, 5, True),
        ("ac_plus_elevator_if_above_1st", {"ac"}, None, True),
        ("ac_plus_elevator_if_above_1st", {"elevator"}, 0, False),
    ],
)
def test_other_must_have_rules(
    spec: SearchSpec, rule: str, features: set[str], floor: int | None, ok: bool
) -> None:
    spec.must_have.rule = rule  # type: ignore[assignment]
    reason = rejection_reason(make_listing(features=features, floor=floor), spec)
    assert (reason is None) is ok


# --- dedupe ---------------------------------------------------------------


def test_haversine_known_distance() -> None:
    # ~111 m per 0.001 degrees latitude
    assert 105 < haversine_m(36.840, -2.46, 36.841, -2.46) < 115


def test_same_flat_on_two_portals_is_duplicate() -> None:
    a = make_listing(source="pisos", source_id="1")
    b = make_listing(source="idealista", source_id="9", price_eur=815, area_m2=82, lat=36.8405)
    assert is_duplicate(a, b)


@pytest.mark.parametrize(
    "overrides",
    [
        {"price_eur": 900},
        {"bedrooms": 3},
        {"area_m2": 100},
        {"area_m2": None},
        {"lat": 36.85},
        {"lat": None},
    ],
)
def test_different_flats_are_not_duplicates(overrides: dict[str, object]) -> None:
    a = make_listing(source_id="1")
    b = make_listing(source="idealista", source_id="2", **overrides)
    assert not is_duplicate(a, b)


def test_listing_is_not_its_own_duplicate() -> None:
    a = make_listing()
    assert not is_duplicate(a, a)


def test_unknown_bedrooms_never_match() -> None:
    a = make_listing(bedrooms=None)
    b = make_listing(source_id="2", bedrooms=None)
    assert not is_duplicate(a, b)


def test_assign_group_reuses_existing_group() -> None:
    existing = make_listing(source="fotocasa", source_id="7", group_id="idealista:3")
    new = make_listing(source="pisos", source_id="1")
    assert assign_group(new, [existing]) == "idealista:3"
    assert assign_group(new, [make_listing(source_id="x", bedrooms=4)]) == "pisos:1"
    no_group = make_listing(source="fotocasa", source_id="8")
    assert assign_group(new, [no_group]) == "fotocasa:8"


@pytest.mark.parametrize(
    "description",
    [
        "NOVIEMBRE A JUNIO SOLO FUNCIONARIOS",
        "SEPTIEMBRE  A JUNIO PROFESORADO.",
        "Disponible hasta junio",
    ],
)
def test_school_year_variants_are_short_term(spec: SearchSpec, description: str) -> None:
    reason = rejection_reason(make_listing(description=description), spec)
    assert reason is not None and reason.startswith("short-term")


@pytest.mark.parametrize(
    "description",
    [
        "¡Se busca compañero/a de piso! Para compartir habitación.",
        "Se alquila piso bien comunicado, cada habitación a 300€mes",
        "Solo CHICAS Habitación 10m, con cama doble",
        "Se alquilan 4 habitaciones amuebladas en piso compartido",
    ],
)
def test_room_shares_are_rejected(spec: SearchSpec, description: str) -> None:
    reason = rejection_reason(make_listing(description=description), spec)
    assert reason is not None and reason.startswith("room share")


def test_normal_listing_mentioning_rooms_passes(spec: SearchSpec) -> None:
    text = "Piso de 3 habitaciones, una de ellas en suite, cerca de la playa"
    assert rejection_reason(make_listing(description=text), spec) is None


def test_commute_address_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from scraper.config import load_spec

    monkeypatch.delenv("COMMUTE_ADDRESS", raising=False)
    assert load_spec().commute.address is None  # never stored in the repo
    monkeypatch.setenv("COMMUTE_ADDRESS", "Somewhere 1, Almería")
    assert load_spec().commute.address == "Somewhere 1, Almería"


def test_regroup_merges_whole_cards_into_the_oldest() -> None:
    from datetime import UTC, datetime, timedelta

    from scraper.dedupe import regroup

    t0 = datetime(2026, 11, 25, tzinfo=UTC)
    text = " ".join(f"palabra{i}" for i in range(30))
    old_a = make_listing(
        source="pisos", source_id="1", group_id="pisos:1", first_seen=t0, description=text
    )
    old_b = make_listing(
        source="enalquiler", source_id="2", group_id="pisos:1", first_seen=t0, description=text
    )
    # A second multi-listing card for the same flat: pins ~1 km away, same text.
    newer_a = make_listing(
        source="fotocasa",
        source_id="3",
        group_id="fotocasa:3",
        first_seen=t0 + timedelta(hours=1),
        lat=36.85,
        description=text,
    )
    newer_b = make_listing(
        source="pisos",
        source_id="4",
        group_id="fotocasa:3",
        first_seen=t0 + timedelta(hours=2),
        lat=36.85,
        description=text,
    )
    other = make_listing(source="fotocasa", source_id="5", group_id=None, lat=37.5, first_seen=None)
    result = regroup([newer_a, old_b, newer_b, old_a, other])
    assert result.moves == {"fotocasa:3": "pisos:1"}
    assert sorted(x.id for x in result.changed) == ["fotocasa:3", "pisos:4"]
    assert {newer_a.group_id, newer_b.group_id, old_a.group_id} == {"pisos:1"}
    again = regroup([newer_a, old_b, newer_b, old_a, other])
    assert again.moves == {} and again.changed == []  # idempotent


def test_regroup_prefers_known_first_seen_and_breaks_ties_by_id() -> None:
    from datetime import UTC, datetime

    from scraper.dedupe import regroup

    t0 = datetime(2026, 11, 25, tzinfo=UTC)
    unknown = make_listing(source="a", source_id="1", group_id="a:1", first_seen=None)
    known = make_listing(source="b", source_id="2", group_id="b:2", first_seen=t0)
    assert regroup([unknown, known]).moves == {"a:1": "b:2"}
    same_a = make_listing(source="c", source_id="1", group_id="c:1", first_seen=t0)
    same_b = make_listing(source="d", source_id="1", group_id="d:1", first_seen=t0)
    assert regroup([same_b, same_a]).moves == {"d:1": "c:1"}
    unknown_a = make_listing(source="a", source_id="1", group_id="a:1", first_seen=None)
    unknown_e = make_listing(source="e", source_id="1", group_id="e:1", first_seen=None)
    assert regroup([unknown_e, unknown_a]).moves == {"e:1": "a:1"}


def test_description_match_overrides_distance_but_not_size() -> None:
    from scraper.dedupe import description_similarity

    text = " ".join(f"word{i}" for i in range(40))
    a = make_listing(source_id="1", description=text)
    far = make_listing(source="x", source_id="2", description=text, lat=36.95)  # ~12 km away
    assert description_similarity(a, far) == 1.0 and is_duplicate(a, far)
    template = " ".join(f"word{i}" for i in range(25)) + " " + " ".join(f"o{i}" for i in range(15))
    assert description_similarity(a, make_listing(source_id="3", description=template)) < 0.9
    other_size = make_listing(source="x", source_id="4", description=text, lat=36.95, area_m2=95)
    assert not is_duplicate(a, other_size)  # same agency template, different flat
    short = make_listing(source="x", source_id="5", description="piso bonito", lat=36.95)
    assert description_similarity(make_listing(description="piso bonito"), short) == 0.0
