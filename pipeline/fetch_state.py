#!/usr/bin/env python3
"""Fetch, enrich, and store events for a single target state.

Runs only the Serper queries for the given state code, then enriches,
deduplicates, stores, and syncs those events — leaving all other state
data untouched.

Usage:
    python3 -m pipeline.fetch_state --state WV

Required environment variables: SERPER_API_KEY, MEILI_MASTER_KEY
Optional: MEILI_URL, DB_PATH, DATA_DIR, DRY_RUN
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .constants import COUNTIES, EVENT_TYPES, STATE_NAMES, STATE_ORDER
from .dedup import exact_dedup, fuzzy_merge_results
from .enrich import Enricher
from .fetchers import serper as serper_fetcher
from .fetchers import url_enrich
from .models import EventItem
from .store import Store
from .sync import MeilisearchSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

_PLACEHOLDER_KEY_FRAGMENT = "change-me"
_ALLOWED_MEILI_SCHEMES = ("http://", "https://")
_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch events for a single state")
    parser.add_argument(
        "--state",
        required=True,
        metavar="XX",
        help="Two-letter state code (e.g. WV)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls and writes")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    state = args.state.upper()
    dry_run = args.dry_run or os.environ.get("DRY_RUN", "").lower() == "true"

    if state not in STATE_ORDER:
        logger.error(
            "State %r is not a configured target. Valid states: %s",
            state,
            ", ".join(STATE_ORDER),
        )
        sys.exit(1)

    serper_api_key = os.environ.get("SERPER_API_KEY", "")
    meili_master_key = os.environ.get("MEILI_MASTER_KEY", "")
    meili_url = os.environ.get("MEILI_URL", "http://hiss-meilisearch:7700")
    db_path = os.environ.get("DB_PATH", "/data/hiss.db")
    data_dir = os.environ.get("DATA_DIR", str(_DEFAULT_DATA_DIR))

    if not dry_run:
        missing = [
            k
            for k, v in [
                ("SERPER_API_KEY", serper_api_key),
                ("MEILI_MASTER_KEY", meili_master_key),
            ]
            if not v
        ]
        if missing:
            logger.error("Missing required env vars: %s", ", ".join(missing))
            sys.exit(1)
        if not any(meili_url.startswith(s) for s in _ALLOWED_MEILI_SCHEMES):
            logger.error("MEILI_URL must start with http:// or https://: %r", meili_url)
            sys.exit(1)
        if _PLACEHOLDER_KEY_FRAGMENT in meili_master_key:
            logger.error("MEILI_MASTER_KEY appears to be a placeholder — set a real key")
            sys.exit(1)

    logger.info(
        "=== fetch_state: %s (%s) dry_run=%s ===", state, STATE_NAMES[state], dry_run
    )

    queries = serper_fetcher.build_queries_for_state(COUNTIES[state], state, EVENT_TYPES)
    logger.info("Built %d Serper queries for %s", len(queries), state)

    events = serper_fetcher.fetch_all(
        serper_api_key, queries, search_state=state, dry_run=dry_run
    )
    logger.info("Serper raw: %d events", len(events))

    if not events and not dry_run:
        logger.warning("No events fetched for %s — nothing to store", state)
        return

    # URL dedup: keep best event per URL (highest page_score, longest name as tiebreaker)
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
    logger.info("After URL dedup: %d events", len(events))

    fetched_at = datetime.now(timezone.utc).isoformat()
    year_prefix = str(date.today().year)

    if not dry_run:
        enricher = Enricher(data_dir)
        url_updated = url_enrich.enrich_from_urls(events)
        logger.info("URL enrichment: updated %d events", url_updated)

        for event in events:
            event.fetched_at = fetched_at
            enricher.enrich(event)

    events = [e for e in events if not e.start_date or e.start_date >= f"{year_prefix}-01-01"]
    events = [e for e in events if e.state in STATE_ORDER]
    logger.info("After date+state filter: %d events", len(events))

    events = exact_dedup(events)
    events = fuzzy_merge_results(events)
    logger.info("After dedup: %d events", len(events))

    if dry_run:
        logger.info("[dry-run] Would store and sync %d events for %s", len(events), state)
        return

    url_to_winner: dict[str, str] = {
        e.primary_url: e.event_id for e in events if e.primary_url
    }

    store = Store(db_path)
    syncer = MeilisearchSync(meili_url, meili_master_key)
    try:
        written = store.upsert_events(events)
        logger.info("Stored %d events", written)

        stale_ids = store.url_dedup_cleanup(url_to_winner)
        if stale_ids:
            syncer.delete_documents(stale_ids)
            logger.info("URL cross-run dedup: removed %d stale events", len(stale_ids))

        purged_ids = store.purge_expired(days=30)
        if purged_ids:
            syncer.delete_documents(purged_ids)

        syncer.configure_index()
        synced = syncer.sync_from_store(store)
        logger.info("Synced %d events to Meilisearch", synced)
    finally:
        store.close()

    logger.info("=== fetch_state complete for %s ===", state)


if __name__ == "__main__":
    main()
