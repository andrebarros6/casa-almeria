"""Interface every portal adapter implements."""

from __future__ import annotations

from typing import Protocol

from scraper.config import SearchSpec
from scraper.models import Listing, Stub


class Source(Protocol):
    name: str
    runs_on: str  # "cloud" (GitHub Actions) or "local" (the owner's PC)
    # Optional: set `free_details = True` when fetch_detail makes no network request
    # (data already came with the search page), so the per-run detail cap doesn't apply.

    def search(self, spec: SearchSpec) -> list[Stub]:
        """Return every listing on the portal's results pages for the spec."""
        ...

    def fetch_detail(self, stub: Stub, spec: SearchSpec) -> Listing:
        """Fetch and parse the listing's detail page."""
        ...
