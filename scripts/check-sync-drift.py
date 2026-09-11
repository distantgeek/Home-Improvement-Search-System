#!/usr/bin/env python3
"""Compare SQLite synced-event count against Meilisearch document count.

Ghost documents accumulate in Meilisearch when a deletion call fails
(purge_expired / url_dedup_cleanup) — the SQLite row is gone but the index
doc survives. This script detects that drift and can reconcile it.

Usage (from repo root):
    python3 scripts/check-sync-drift.py                 # report only
    python3 scripts/check-sync-drift.py --reconcile     # delete ghost docs

Environment:
    DB_PATH            SQLite path (default: /data/hiss.db)
    MEILI_URL          Meilisearch URL (default: http://hiss-meilisearch:7700)
    MEILI_MASTER_KEY   Meilisearch master key (required for --reconcile)

Exit codes:
    0  no drift (or reconciled successfully)
    1  drift detected (report mode)
    2  configuration / connection error
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.store import Store  # noqa: E402
from pipeline.sync import INDEX_UID, MeilisearchSync  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="delete ghost documents from Meilisearch (requires MEILI_MASTER_KEY)",
    )
    args = parser.parse_args()

    db_path = os.environ.get("DB_PATH", "/data/hiss.db")
    meili_url = os.environ.get("MEILI_URL", "http://hiss-meilisearch:7700")
    meili_master_key = os.environ.get("MEILI_MASTER_KEY", "")

    if args.reconcile and not meili_master_key:
        logger.error("MEILI_MASTER_KEY is required for --reconcile")
        return 2

    try:
        store = Store(db_path)
    except RuntimeError as exc:
        logger.error("Cannot open SQLite store: %s", exc)
        return 2

    try:
        sqlite_count = store.count()
        synced_count = store._conn.execute(
            "SELECT COUNT(*) FROM events WHERE synced = 1"
        ).fetchone()[0]
    finally:
        store.close()

    try:
        syncer = MeilisearchSync(meili_url, meili_master_key or "x")
        stats = syncer._client.index(INDEX_UID).get_stats()
        meili_count = stats["numberOfDocuments"]
    except Exception as exc:
        logger.error("Cannot reach Meilisearch at %s: %s", meili_url, exc)
        return 2

    logger.info("SQLite events:        %d", sqlite_count)
    logger.info("SQLite synced=1:      %d", synced_count)
    logger.info("Meilisearch docs:     %d", meili_count)

    if meili_count == sqlite_count:
        logger.info("No drift — SQLite and Meilisearch are in sync.")
        return 0

    if meili_count > sqlite_count:
        ghost_count = meili_count - sqlite_count
        logger.warning(
            "DRIFT: Meilisearch has %d ghost documents (not in SQLite).",
            ghost_count,
        )
        if args.reconcile:
            logger.info("Reconciling: clearing index and re-syncing from SQLite…")
            syncer.configure_index()
            syncer.clear_index()
            store = Store(db_path)
            try:
                store._conn.execute("UPDATE events SET synced = 0")
                store._conn.commit()
                synced = syncer.sync_from_store(store)
            finally:
                store.close()
            logger.info("Re-synced %d events. Drift resolved.", synced)
            return 0
        logger.info("Run with --reconcile to clear ghosts and re-sync.")
        return 1

    missing_count = sqlite_count - meili_count
    logger.warning(
        "DRIFT: Meilisearch is missing %d documents that exist in SQLite.",
        missing_count,
    )
    if args.reconcile:
        logger.info("Reconciling: clearing index and re-syncing from SQLite…")
        syncer.configure_index()
        syncer.clear_index()
        store = Store(db_path)
        try:
            store._conn.execute("UPDATE events SET synced = 0")
            store._conn.commit()
            synced = syncer.sync_from_store(store)
        finally:
            store.close()
        logger.info("Re-synced %d events. Drift resolved.", synced)
        return 0
    logger.info("Run with --reconcile to re-sync from SQLite.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
