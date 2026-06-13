#!/usr/bin/env python3
"""Re-process existing events in SQLite with updated pipeline logic.

Re-runs enrichment (state correction via ZIP), applies URL dedup,
drops events with empty or non-target state, and re-syncs to Meilisearch.

Does NOT re-fetch from Serper or any other source.

Usage:
    python3 -m pipeline.reprocess
"""

import json
import logging
import os
import sys

from .constants import STATE_ORDER
from .dedup import exact_dedup, fuzzy_merge_results
from .enrich import Enricher
from .models import EventItem
from .normalize import (
    _NON_TARGET_STATES,
    _ADDR_STATE_RE,
    _TARGET_ABBREVIATIONS,
    _NAME_DATE_RE,
    _YEAR_IN_RANGE_RE,
    parse_dates,
)
import re
from .store import Store
from .sync import MeilisearchSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _row_to_event(row: dict) -> EventItem:
    return EventItem(
        event_id=row["event_id"],
        dedup_key=row["dedup_key"],
        name=row["name"],
        start_date=row.get("start_date", ""),
        end_date=row.get("end_date", ""),
        venue=row.get("venue", ""),
        city=row.get("city", ""),
        state=row.get("state", ""),
        county=row.get("county", ""),
        county_full=row.get("county_full", ""),
        zip=row.get("zip", ""),
        event_type=row.get("event_type", ""),
        primary_url=row.get("primary_url", ""),
        source_type=row.get("source_type", ""),
        source_queries=json.loads(row.get("source_queries", "[]") or "[]"),
        sources=json.loads(row.get("sources", "[]") or "[]"),
        attendance=row.get("attendance", ""),
        contact=row.get("contact", ""),
        page_score=row.get("page_score", 0) or 0,
        fetched_at=row.get("fetched_at", ""),
        synced=row.get("synced", 0),
        addr_full=row.get("addr_full", ""),
    )


def main():
    db_path = os.environ.get("DB_PATH", "/data/hiss.db")
    data_dir = os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )
    meili_url = os.environ.get("MEILI_URL", "http://hiss-meilisearch:7700")
    meili_master_key = os.environ.get("MEILI_MASTER_KEY", "")

    if not meili_master_key:
        logger.error("MEILI_MASTER_KEY is required")
        sys.exit(1)

    store = Store(db_path)
    enricher = Enricher(data_dir)

    columns = [
        desc[0]
        for desc in store._conn.execute("SELECT * FROM events LIMIT 0").description
    ]
    rows = store._conn.execute("SELECT * FROM events").fetchall()
    logger.info("Loaded %d events from SQLite", len(rows))

    events = []
    for row in rows:
        d = dict(zip(columns, row))
        events.append(_row_to_event(d))

    # ── Date extraction from event names ──────────────────────────────────────
    # Re-run the name-based date extraction for events with empty start_date.
    # This was added after the original fetch, so existing events in the DB
    # may have a date like "Oct 10 & 11 2026" in their name but no start_date.
    pre_date = len(events)
    date_filled = 0
    for event in events:
        if event.start_date:
            continue
        m = _NAME_DATE_RE.search(event.name)
        if m:
            date_str = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", m.group(0))
            date_str = date_str.replace("&", "-")
            start_date, end_date = parse_dates(date_str)
            if start_date:
                event.start_date = start_date
                event.end_date = end_date or start_date
                date_filled += 1
                continue
        ym = _YEAR_IN_RANGE_RE.search(event.name)
        if ym:
            event.start_date = f"{ym.group(1)}-01-01"
            event.end_date = event.start_date
            date_filled += 1
    if date_filled:
        logger.info("Extracted dates from event names for %d events", date_filled)

    # ── Re-enrich (state correction via ZIP) ──────────────────────────────────
    logger.info("Re-enriching %d events…", len(events))
    for event in events:
        enricher.enrich(event)

    # ── URL dedup: keep best event per primary_url ────────────────────────────
    pre_url_dedup = len(events)
    by_url: dict[str, EventItem] = {}
    no_url: list[EventItem] = []
    for event in events:
        url = event.primary_url
        if not url:
            no_url.append(event)
            continue
        if url not in by_url:
            by_url[url] = event
        else:
            existing = by_url[url]
            if event.page_score > existing.page_score or (
                event.page_score == existing.page_score
                and len(event.name) > len(existing.name)
            ):
                by_url[url] = event
    events = list(by_url.values()) + no_url
    url_dedup_dropped = pre_url_dedup - len(events)
    if url_dedup_dropped:
        logger.info("URL dedup: dropped %d events", url_dedup_dropped)

    # ── State filter: drop events with empty or non-target state ──────────────
    pre_state = len(events)
    events = [e for e in events if e.state in STATE_ORDER]
    state_dropped = pre_state - len(events)
    if state_dropped:
        logger.info("State filter: dropped %d events", state_dropped)

    # ── Non-target state content filter ──────────────────────────────────────
    # Drop events whose title, URL, or address mentions a non-target state.
    # This catches events that were fetched by a KS/MO query but are actually
    # in Nebraska, Iowa, Colorado, etc. — the same check normalize_event now
    # does at fetch time, applied retroactively to existing data.
    pre_content = len(events)
    filtered = []
    for event in events:
        combined_lower = f"{event.name} {event.addr_full} {event.primary_url}".lower()
        rejected = False
        for nt_name in _NON_TARGET_STATES:
            if nt_name.lower() in combined_lower:
                rejected = True
                break
        if not rejected:
            combined_orig = f"{event.name} {event.addr_full} {event.primary_url}"
            for m in _ADDR_STATE_RE.finditer(combined_orig):
                if m.group(1) not in _TARGET_ABBREVIATIONS:
                    rejected = True
                    break
        if not rejected:
            filtered.append(event)
    events = filtered
    content_dropped = pre_content - len(events)
    if content_dropped:
        logger.info(
            "Non-target state content filter: dropped %d events", content_dropped
        )

    # ── Re-dedup ──────────────────────────────────────────────────────────────
    events = exact_dedup(events)
    logger.info("After exact dedup: %d", len(events))
    events = fuzzy_merge_results(events)
    logger.info("After fuzzy dedup: %d", len(events))

    # ── Delete all existing events and re-insert ──────────────────────────────
    logger.info("Replacing database with %d reprocessed events", len(events))
    store._conn.execute("DELETE FROM events")
    store._conn.commit()
    written = store.upsert_events(events)
    logger.info("Upserted %d events", written)

    purged = store.purge_expired(days=30)
    if purged:
        logger.info("Purged %d expired events", purged)

    # ── Full Meilisearch re-sync ──────────────────────────────────────────────
    sync = MeilisearchSync(meili_url, meili_master_key)
    sync.configure_index()

    # Mark all events as unsynced so sync_from_store picks them up
    store._conn.execute("UPDATE events SET synced = 0")
    store._conn.commit()

    synced = sync.sync_from_store(store)
    logger.info("Synced %d events to Meilisearch", synced)

    store.close()
    logger.info("=== Reprocess complete ===")


if __name__ == "__main__":
    main()
