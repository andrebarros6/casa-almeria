from __future__ import annotations

import httpx
import pytest

from scraper.geo import USER_AGENT, commute_point, geocode, parse_latlng


def client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_parse_latlng() -> None:
    assert parse_latlng("36.84, -2.46") == (36.84, -2.46)
    assert parse_latlng("") is None
    assert parse_latlng("abc,def") is None
    assert parse_latlng("1,2,3") is None
    assert parse_latlng("95,0") is None


def test_geocode_sends_generic_client_and_parses_result() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"lat": "36.83", "lon": "-2.45"}])

    assert geocode("Some street, Almería", client(handler)) == (36.83, -2.45)
    req = seen[0]
    assert req.headers["User-Agent"] == USER_AGENT
    assert req.url.params["countrycodes"] == "es" and req.url.params["limit"] == "1"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json=[]), httpx.Response(503), httpx.Response(200, text="not json")],
)
def test_geocode_failures_return_none(response: httpx.Response) -> None:
    assert geocode("x", client(lambda r: response)) is None


def test_commute_point_prefers_override(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=[{"lat": "1", "lon": "2"}])

    monkeypatch.setenv("COMMUTE_LATLNG", "36.1,-2.2")
    assert commute_point("anything", client(handler)) == (36.1, -2.2)
    monkeypatch.delenv("COMMUTE_LATLNG")
    assert commute_point(None, client(handler)) is None
    assert calls == []
    assert commute_point("street", client(handler)) == (1.0, 2.0)
