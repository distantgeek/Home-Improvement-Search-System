"""SQLite canonical data store."""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .models import EventItem

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id       TEXT PRIMARY KEY,
    dedup_key      TEXT NOT NULL,
    name           TEXT NOT NULL,
    start_date     TEXT,
    end_date       TEXT,
    venue          TEXT,
    city           TEXT,
    state          TEXT,
    county         TEXT,
    county_full    TEXT,
    zip            TEXT,
    event_type     TEXT,
    primary_url    TEXT,
    source_type    TEXT,
    source_queries TEXT,
    sources        TEXT,
    attendance     TEXT,
    contact        TEXT,
    page_score     INTEGER DEFAULT 0,
    fetched_at     TEXT,
    synced         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_state      ON events(state);
CREATE INDEX IF NOT EXISTS idx_events_county     ON events(county);
CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date);
CREATE INDEX IF NOT EXISTS idx_events_end_date   ON events(end_date);
CREATE INDEX IF NOT EXISTS idx_events_synced     ON events(synced);
"""

_UPSERT_SQL = """
INSERT INTO events (
    event_id, dedup_key, name, start_date, end_date,
    venue, city, state, county, county_full, zip,
    event_type, primary_url, source_type, source_queries,
    sources, attendance, contact, page_score, fetched_at, synced
) VALUES (
    :event_id, :dedup_key, :name, :start_date, :end_date,
    :venue, :city, :state, :county, :county_full, :zip,
    :event_type, :primary_url, :source_type, :source_queries,
    :sources, :attendance, :contact, :page_score, :fetched_at, 0
)
ON CONFLICT(event_id) DO UPDATE SET
    name           = excluded.name,
    start_date     = excluded.start_date,
    end_date       = excluded.end_date,
    venue          = excluded.venue,
    city           = excluded.city,
    state          = excluded.state,
    county         = excluded.county,
    county_full    = excluded.county_full,
    zip            = excluded.zip,
    event_type     = excluded.event_type,
    primary_url    = excluded.primary_url,
    source_type    = excluded.source_type,
    source_queries = excluded.source_queries,
    sources        = excluded.sources,
    attendance     = excluded.attendance,
    contact        = excluded.contact,
    page_score     = excluded.page_score,
    fetched_at     = excluded.fetched_at,
    synced         = 0
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                f"Cannot open database at {self.db_path!r}: {exc}"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            raise RuntimeError(f"Failed to initialise database schema: {exc}") from exc

    def upsert_events(self, events: list[EventItem]) -> int:
        """UPSERT events, mark all as unsynced. Returns count written."""
        if not events:
            return 0
        rows = [e.to_db_row() for e in events]
        try:
            self._conn.executemany(_UPSERT_SQL, rows)
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            self._conn.rollback()
            raise RuntimeError(f"Failed to upsert events: {exc}") from exc
        return len(rows)

    def purge_expired(self, days: int = 30) -> int:
        """Delete events whose end_date is more than `days` days in the past."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        try:
            cur = self._conn.execute(
                "DELETE FROM events WHERE end_date IS NOT NULL AND end_date != '' AND end_date < ?",
                (cutoff,),
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            self._conn.rollback()
            raise RuntimeError(f"Failed to purge expired events: {exc}") from exc
        count = cur.rowcount
        if count:
            logger.info("Purged %d expired events (end_date < %s)", count, cutoff)
        return count

    def get_unsynced(self, limit: int = 1000) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM events WHERE synced = 0 LIMIT ?", (limit,)
        )
        return [dict(row) for row in cur.fetchall()]

    def mark_synced(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        try:
            self._conn.executemany(
                "UPDATE events SET synced = 1 WHERE event_id = ?",
                [(eid,) for eid in event_ids],
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            logger.error("Failed to mark %d events synced: %s", len(event_ids), exc)
            raise RuntimeError(f"Failed to mark events synced: {exc}") from exc

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception as exc:
            logger.warning("Error closing database connection: %s", exc)
