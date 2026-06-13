#!/usr/bin/env python3
"""Re-run enrichment on existing events in SQLite.

Reads all events with missing ZIP/county/city from the database,
runs url_enrich and enrich on them, upserts the results back,
and syncs to Meilisearch.

Usage:
    python3 -m pipeline.reenrich
"""

import os
import sys
import logging

from .store import Store
from .enrich import Enricher
from .fetchers.url_enrich import enrich_from_urls
from .models import EventItem
from .sync import MeilisearchSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    db_path = os.environ.get("DB_PATH", "/data/hiss.db")
    data_dir = os.environ.get(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )
    meili_url = os.environ.get("MEILI_URL", "http://hiss-meilisearch:7700")
    meili_master_key = os.environ.get("MEILI_MASTER_KEY", "")

    store = Store(db_path)
    enricher = Enricher(data_dir)

    rows = store._conn.execute(
        "SELECT * FROM events WHERE zip IS NULL OR zip = '' "
        "OR county IS NULL OR county = '' "
        "OR city IS NULL OR city = ''"
    ).fetchall()
    columns = [
        desc[0]
        for desc in store._conn.execute("SELECT * FROM events LIMIT 0").description
    ]
    logger.info("Events needing enrichment: %d", len(rows))

    events = []
    for row in rows:
        d = dict(zip(columns, row))
        e = EventItem(
            name=d["name"],
            primary_url=d.get("primary_url", ""),
            venue=d.get("venue", ""),
            city=d.get("city", ""),
            state=d.get("state", ""),
            county=d.get("county", ""),
            county_full=d.get("county_full", ""),
            zip=d.get("zip", ""),
            event_type=d.get("event_type", ""),
            addr_full=d.get("addr_full", ""),
            source_type=d.get("source_type", ""),
            page_score=d.get("page_score", 0),
        )
        events.append(e)

    logger.info("Running url_enrich on %d events...", len(events))
    enriched_count = enrich_from_urls(events)
    logger.info("URL enrich result: %d events enriched", enriched_count)

    for e in events:
        try:
            enricher.enrich(e)
        except KeyError:
            logger.warning("Skipping enrich for event with unknown state: %s", e.state)

    logger.info("Upserting enriched events...")
    store.upsert_events(events)

    logger.info("Syncing to Meilisearch...")
    sync = MeilisearchSync(meili_url, meili_master_key)
    sync.sync_from_store(store)

    logger.info("Re-enrichment complete")


if __name__ == "__main__":
    main()
