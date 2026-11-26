"""Turn the commute address into coordinates (OpenStreetMap Nominatim).

One request per run, with a generic client name (Nominatim's usage policy asks clients
to identify themselves; no personal details are sent besides the address itself).
COMMUTE_LATLNG="lat,lng" in the environment skips the request entirely.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "casa-almeria-rental-finder/1.0"

Point = tuple[float, float]


def parse_latlng(text: str) -> Point | None:
    try:
        lat, lng = (float(part) for part in text.split(","))
    except ValueError:
        return None
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng
    return None


def geocode(address: str, client: httpx.Client | None = None) -> Point | None:
    http = client or httpx.Client(timeout=20)
    try:
        resp = http.get(
            NOMINATIM,
            params={"q": address, "format": "jsonv2", "limit": "1", "countrycodes": "es"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es"},
        )
        resp.raise_for_status()
        results = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("geocoding failed: %s", type(exc).__name__)
        return None
    if not results:
        log.warning("geocoding found nothing for the commute address")
        return None
    return float(results[0]["lat"]), float(results[0]["lon"])


def commute_point(address: str | None, client: httpx.Client | None = None) -> Point | None:
    """COMMUTE_LATLNG wins; otherwise geocode the address; None if neither works."""
    override = parse_latlng(os.environ.get("COMMUTE_LATLNG", ""))
    if override:
        return override
    if not address:
        return None
    return geocode(address, client)
