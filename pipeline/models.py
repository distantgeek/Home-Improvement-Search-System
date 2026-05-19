from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def make_event_id(dedup_key: str) -> str:
    return hashlib.sha256(dedup_key.encode()).hexdigest()


@dataclass
class EventItem:
    # ── Identity ─────────────────────────────────────────────────────────────
    event_id: str = ""
    dedup_key: str = ""

    # ── Core ─────────────────────────────────────────────────────────────────
    name: str = ""
    start_date: str = ""   # YYYY-MM-DD or ""
    end_date: str = ""     # YYYY-MM-DD or "", defaults to start_date

    # ── Location ─────────────────────────────────────────────────────────────
    venue: str = ""
    city: str = ""
    state: str = ""        # VA | MD | PA | DC | NJ | DE
    county: str = ""       # "Frederick" — no suffix
    county_full: str = ""  # "Frederick County" — with suffix
    zip: str = ""          # 5-digit or ""

    # ── Classification ───────────────────────────────────────────────────────
    event_type: str = ""

    # ── Provenance ───────────────────────────────────────────────────────────
    primary_url: str = ""
    source_type: str = ""          # "eventbrite" | "serper_events" | "serper_organic"
    source_queries: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # alternate URLs

    # ── Supplemental ─────────────────────────────────────────────────────────
    attendance: str = ""
    contact: str = ""

    # ── Pipeline bookkeeping ─────────────────────────────────────────────────
    page_score: int = 0
    fetched_at: str = ""
    synced: int = 0

    # ── Transient: used during enrichment, not persisted to Meilisearch ──────
    addr_full: str = field(default="", repr=False)

    def to_db_row(self) -> dict:
        """Flat dict for SQLite storage (JSON-encodes list fields)."""
        return {
            "event_id": self.event_id,
            "dedup_key": self.dedup_key,
            "name": self.name,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "venue": self.venue,
            "city": self.city,
            "state": self.state,
            "county": self.county,
            "county_full": self.county_full,
            "zip": self.zip,
            "event_type": self.event_type,
            "primary_url": self.primary_url,
            "source_type": self.source_type,
            "source_queries": json.dumps(self.source_queries),
            "sources": json.dumps(self.sources),
            "attendance": self.attendance,
            "contact": self.contact,
            "page_score": self.page_score,
            "fetched_at": self.fetched_at,
            "synced": self.synced,
        }
