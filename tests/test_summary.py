from __future__ import annotations

from datetime import UTC, datetime

from scraper.config import SearchSpec
from scraper.summary import build_summary, reason_key


def test_reason_keys() -> None:
    assert reason_key("short-term: 'verano'") == "short_term"
    assert reason_key("short-term: portal flag") == "short_term"
    assert reason_key("price 1100 > 1000") == "price"
    assert reason_key("must-have (elevator_or_ac)") == "must_have"
    assert reason_key("room share: 'solo chicas'") == "room_share"
    assert reason_key("bedrooms 1 < 2") == "bedrooms"
    assert reason_key("type house") == "type"
    assert reason_key("something new") == "other"


def test_build_summary(spec: SearchSpec) -> None:
    now = datetime(2026, 11, 26, 7, tzinfo=UTC)
    reasons = [
        None,
        None,
        "price 1100 > 1000",
        "short-term: 'verano'",
        "short-term: portal flag",
        "??",
    ]
    s = build_summary(spec, reasons, now)
    assert s["criteria"]["max_price_eur"] == 1000
    assert s["criteria"]["min_bedrooms"] == 2
    assert s["criteria"]["areas"] == ["Almería ciudad", "Poniente", "Levante / Cabo de Gata"]
    assert s["criteria"]["must_have"] == "elevator_or_ac"
    assert s["counts"] == {
        "seen": 6,
        "matching": 2,
        "discarded": {"short_term": 2, "price": 1, "other": 1},
    }
    assert list(s["counts"]["discarded"]) == ["short_term", "price", "other"]  # display order
    assert s["updated_at"] == now.isoformat()
