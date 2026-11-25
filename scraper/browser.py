"""Real-Chrome fetching for portals that need a browser (runs on the owner's PC only).

Uses a persistent Chrome profile so cookies carry over between days, and behaves
like a person: one page at a time, long random pauses, some scrolling. If a portal
shows a bot challenge we stop immediately (SourceBlocked) and never retry in a loop.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from scraper.http import SourceBlocked

PROFILE_DIR = Path(__file__).resolve().parent.parent / "local" / "chrome-profile"
BLOCK_RE = re.compile(
    r"captcha-delivery\.com|geo\.captcha|px-captcha|Pardon Our Interruption|unusual traffic",
    re.IGNORECASE,
)


class Mouse(Protocol):
    def wheel(self, delta_x: float, delta_y: float) -> None: ...


class Page(Protocol):
    @property
    def mouse(self) -> Mouse: ...

    def goto(self, url: str, *, timeout: Any = None, wait_until: Any = None) -> Any: ...
    def content(self) -> str: ...


class BrowserFetcher:
    def __init__(
        self,
        page_factory: Callable[[], tuple[Page, Callable[[], None]]] | None = None,
        min_wait: float = 6.0,
        max_wait: float = 12.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._factory = page_factory or _launch_chrome
        self._page: Page | None = None
        self._close: Callable[[], None] | None = None
        self.min_wait, self.max_wait = min_wait, max_wait
        self._sleep = sleep

    def get(self, url: str) -> str:
        if self._page is None:
            self._page, self._close = self._factory()
        else:
            self._sleep(random.uniform(self.min_wait, self.max_wait))
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._sleep(random.uniform(3, 6))
        for _ in range(random.randint(2, 4)):
            self._page.mouse.wheel(0, random.randint(400, 900))
            self._sleep(random.uniform(0.6, 1.5))
        html = self._page.content()
        status = getattr(response, "status", 200)
        if status in (403, 429) or BLOCK_RE.search(html[:20_000]):
            raise SourceBlocked(f"bot challenge ({status}) for {url}")
        return html

    def close(self) -> None:
        if self._close:
            self._close()
        self._page = self._close = None


def _launch_chrome() -> tuple[Page, Callable[[], None]]:  # pragma: no cover - needs a desktop
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        locale="es-ES",
        viewport={"width": 1366, "height": 850},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def close() -> None:
        ctx.close()
        pw.stop()

    return page, close
