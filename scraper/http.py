"""Polite HTTP fetching: realistic headers, random delays, block detection."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
BLOCK_MARKERS = ("captcha-delivery.com", "geo.captcha", "datadome", "cf-challenge")


class SourceBlocked(RuntimeError):
    """The portal refused us (403/429 or a bot-challenge page)."""


class Fetcher:
    def __init__(
        self,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_delay, self.max_delay = min_delay, max_delay
        self._sleep = sleep
        self._last = 0.0
        self.client = client or httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es-ES,es;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=True,
            timeout=30,
        )

    def get(self, url: str) -> str:
        wait = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
        if self._last and wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()
        resp = self.client.get(url)
        if resp.status_code in (403, 429):
            raise SourceBlocked(f"{resp.status_code} for {url}")
        resp.raise_for_status()
        text = resp.text
        if any(marker in text[:5000].lower() for marker in BLOCK_MARKERS):
            raise SourceBlocked(f"bot challenge for {url}")
        return text
