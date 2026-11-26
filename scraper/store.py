"""Persistence: Supabase (production) or a JSON file (dry runs and tests)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel

from scraper.models import Lead, Listing

RunStatus = Literal["ok", "blocked", "error"]


class SourceRun(BaseModel):
    source: str
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = "ok"
    found: int = 0
    new: int = 0
    new_matches: int = 0
    updated: int = 0
    gone: int = 0
    error: str | None = None


class Store(Protocol):
    def get_many(self, ids: list[str]) -> dict[str, Listing]: ...
    def active_listings(self) -> list[Listing]: ...
    def upsert(self, listings: Iterable[Listing]) -> None: ...
    def mark_gone(self, source: str, last_seen_before: datetime) -> int: ...
    def record_run(self, run: SourceRun) -> None: ...
    def recent_runs(self, source: str, limit: int) -> list[SourceRun]: ...
    def current_reasons(self) -> list[str | None]: ...
    def save_summary(self, summary: dict[str, Any]) -> None: ...
    def move_reactions(self, moves: dict[str, str]) -> None: ...
    def leads_with_listings(self, stages: list[str]) -> list[tuple[Lead, Listing]]: ...


def merge_notes(a: str | None, b: str | None) -> str | None:
    """Combine two notes when two cards merge; keep each once."""
    parts = [n.strip() for n in (a, b) if n and n.strip()]
    unique = list(dict.fromkeys(parts))
    return " / ".join(unique) or None


def _row(listing: Listing) -> dict[str, Any]:
    row = listing.model_dump(mode="json")
    row["id"] = listing.id
    row["features"] = sorted(listing.features)
    return row


class JsonStore:
    """Keeps everything in memory; optionally persists to a JSON file between runs."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.listings: dict[str, Listing] = {}
        self.runs: list[SourceRun] = []
        self.summary: dict[str, Any] | None = None
        self.leads: list[Lead] = []  # set by tests; dry runs have no leads
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("listings", []):
                listing = Listing.model_validate(row)
                self.listings[listing.id] = listing
            self.runs = [SourceRun.model_validate(r) for r in data.get("runs", [])]

    def get_many(self, ids: list[str]) -> dict[str, Listing]:
        return {i: self.listings[i].model_copy(deep=True) for i in ids if i in self.listings}

    def active_listings(self) -> list[Listing]:
        return [
            item.model_copy(deep=True)
            for item in self.listings.values()
            if not item.gone and item.rejected_reason is None
        ]

    def upsert(self, listings: Iterable[Listing]) -> None:
        for listing in listings:
            self.listings[listing.id] = listing.model_copy(deep=True)
        self._save()

    def mark_gone(self, source: str, last_seen_before: datetime) -> int:
        count = 0
        for item in self.listings.values():
            stale = item.last_seen is not None and item.last_seen < last_seen_before
            if item.source == source and not item.gone and stale:
                item.gone = True
                count += 1
        self._save()
        return count

    def record_run(self, run: SourceRun) -> None:
        self.runs.append(run)
        self._save()

    def recent_runs(self, source: str, limit: int) -> list[SourceRun]:
        runs = sorted((r for r in self.runs if r.source == source), key=lambda r: r.started_at)
        return list(reversed(runs))[:limit]

    def current_reasons(self) -> list[str | None]:
        return [item.rejected_reason for item in self.listings.values() if not item.gone]

    def save_summary(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self._save()

    def move_reactions(self, moves: dict[str, str]) -> None:
        """Dry runs have no reactions."""

    def leads_with_listings(self, stages: list[str]) -> list[tuple[Lead, Listing]]:
        out = []
        for lead in self.leads:
            if lead.stage not in stages:
                continue
            match = next(
                (
                    x
                    for x in self.listings.values()
                    if (x.group_id or x.id) == lead.group_id and not x.gone
                ),
                None,
            )
            if match:
                out.append((lead, match))
        return out

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "listings": [_row(item) for item in self.listings.values()],
            "runs": [r.model_dump(mode="json") for r in self.runs],
            "summary": self.summary,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


class SupabaseStore:
    """Talks to Supabase's REST API (PostgREST) with the service-role key."""

    CHUNK = 100
    PAGE = 1000  # PostgREST returns at most 1000 rows per request by default

    def __init__(self, url: str, service_key: str, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=30)
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": service_key, "Content-Type": "application/json"}
        # Legacy service_role keys are JWTs and also go in Authorization. New-style secret
        # keys (sb_secret_...) are not JWTs and must only be sent as `apikey`.
        if service_key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {service_key}"

    @classmethod
    def from_env(cls) -> SupabaseStore:
        return cls(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        resp = self.client.request(
            method, f"{self.base}/{path}", params=params, json=body, headers=headers
        )
        resp.raise_for_status()
        return resp.json() if resp.content else None

    @staticmethod
    def _in(ids: list[str]) -> str:
        quoted = ",".join('"' + i.replace('"', "") + '"' for i in ids)
        return f"in.({quoted})"

    def get_many(self, ids: list[str]) -> dict[str, Listing]:
        out: dict[str, Listing] = {}
        for start in range(0, len(ids), self.CHUNK):
            chunk = ids[start : start + self.CHUNK]
            rows = self._request("GET", "listings", params={"id": self._in(chunk), "select": "*"})
            for row in rows:
                listing = Listing.model_validate(row)
                out[listing.id] = listing
        return out

    def _get_all(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET every row, page by page (a single GET silently stops at 1000 rows)."""
        rows: list[dict[str, Any]] = []
        while True:
            page = self._request(
                "GET",
                path,
                params={**params, "order": "id", "limit": str(self.PAGE), "offset": str(len(rows))},
            )
            rows.extend(page)
            if len(page) < self.PAGE:
                return rows

    def active_listings(self) -> list[Listing]:
        rows = self._get_all(
            "listings", {"gone": "eq.false", "rejected_reason": "is.null", "select": "*"}
        )
        return [Listing.model_validate(r) for r in rows]

    def upsert(self, listings: Iterable[Listing]) -> None:
        rows = [_row(item) for item in listings]
        for start in range(0, len(rows), self.CHUNK):
            self._request(
                "POST",
                "listings",
                body=rows[start : start + self.CHUNK],
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def mark_gone(self, source: str, last_seen_before: datetime) -> int:
        rows = self._request(
            "PATCH",
            "listings",
            params={
                "source": f"eq.{source}",
                "gone": "eq.false",
                "last_seen": f"lt.{last_seen_before.isoformat()}",
                "select": "id",
            },
            body={"gone": True},
            prefer="return=representation",
        )
        return len(rows or [])

    def record_run(self, run: SourceRun) -> None:
        self._request(
            "POST", "source_runs", body=run.model_dump(mode="json"), prefer="return=minimal"
        )

    def recent_runs(self, source: str, limit: int) -> list[SourceRun]:
        rows = self._request(
            "GET",
            "source_runs",
            params={
                "source": f"eq.{source}",
                "order": "started_at.desc",
                "limit": str(limit),
                "select": "*",
            },
        )
        return [SourceRun.model_validate(r) for r in rows]

    def current_reasons(self) -> list[str | None]:
        rows = self._get_all("listings", {"gone": "eq.false", "select": "id,rejected_reason"})
        return [r["rejected_reason"] for r in rows]

    def save_summary(self, summary: dict[str, Any]) -> None:
        self._request(
            "POST",
            "search_summary",
            body={"id": "latest", **summary},
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def move_reactions(self, moves: dict[str, str]) -> None:
        """Re-key ❤️/❌/notes from absorbed cards onto the surviving card."""
        for old, new in moves.items():
            for row in self._request(
                "GET", "reactions", params={"group_id": f"eq.{old}", "select": "*"}
            ):
                user = row["user_email"]
                existing = self._request(
                    "GET",
                    "reactions",
                    params={"group_id": f"eq.{new}", "user_email": f"eq.{user}", "select": "*"},
                )
                if existing:
                    keep = existing[0]
                    self._request(
                        "PATCH",
                        "reactions",
                        params={"group_id": f"eq.{new}", "user_email": f"eq.{user}"},
                        body={
                            "reaction": keep["reaction"] or row["reaction"],
                            "note": merge_notes(keep["note"], row["note"]),
                        },
                        prefer="return=minimal",
                    )
                    self._request(
                        "DELETE",
                        "reactions",
                        params={"group_id": f"eq.{old}", "user_email": f"eq.{user}"},
                        prefer="return=minimal",
                    )
                else:
                    self._request(
                        "PATCH",
                        "reactions",
                        params={"group_id": f"eq.{old}", "user_email": f"eq.{user}"},
                        body={"group_id": new},
                        prefer="return=minimal",
                    )

    def leads_with_listings(self, stages: list[str]) -> list[tuple[Lead, Listing]]:
        rows = self._request(
            "GET",
            "leads",
            params={
                "stage": f"in.({','.join(stages)})",
                "select": "group_id,stage,stage_at,next_action_at",
            },
        )
        leads = [Lead.model_validate(r) for r in rows]
        if not leads:
            return []
        groups = self._in([lead.group_id for lead in leads])
        rows = self._get_all("listings", {"group_id": groups, "gone": "eq.false", "select": "*"})
        by_group: dict[str, Listing] = {}
        for row in rows:
            listing = Listing.model_validate(row)
            by_group.setdefault(listing.group_id or listing.id, listing)
        return [(lead, by_group[lead.group_id]) for lead in leads if lead.group_id in by_group]
