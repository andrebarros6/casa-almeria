"""Registry of portal adapters."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from scraper.sources.base import Source
from scraper.sources.email_alerts import EmailAlertsSource, email_sources_enabled
from scraper.sources.enalquiler import EnalquilerSource
from scraper.sources.fotocasa import FotocasaSource
from scraper.sources.pisos import PisosSource

REGISTRY: dict[str, Callable[[], Source]] = {
    "pisos": PisosSource,
    "enalquiler": EnalquilerSource,
    "fotocasa": FotocasaSource,
    "idealista": partial(EmailAlertsSource, "idealista"),
    "yaencontre": partial(EmailAlertsSource, "yaencontre"),
    "milanuncios": partial(EmailAlertsSource, "milanuncios"),
}
# Read from alert emails; only included in group runs once the Gmail credentials exist.
EMAIL_SOURCES = {"idealista", "yaencontre", "milanuncios"}


def select(which: str) -> list[Source]:
    """which = "cloud" | "local" | "all" | a comma-separated list of source names."""
    if which in ("all", "cloud", "local"):
        names = [n for n in REGISTRY if n not in EMAIL_SOURCES or email_sources_enabled()]
        sources = [REGISTRY[n]() for n in names]
        return sources if which == "all" else [s for s in sources if s.runs_on == which]
    wanted = {n.strip() for n in which.split(",")}
    unknown = wanted - REGISTRY.keys()
    if unknown:
        raise ValueError(f"unknown sources: {', '.join(sorted(unknown))}")
    return [REGISTRY[n]() for n in REGISTRY if n in wanted]
