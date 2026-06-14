"""Meilisearch index configuration and sync from SQLite store."""

from __future__ import annotations

import json
import logging

import meilisearch
import meilisearch.errors

from .models import EventItem

logger = logging.getLogger(__name__)

INDEX_UID = "events"
PRIMARY_KEY = "id"
BATCH_SIZE = 100

_INDEX_SETTINGS = {
    "filterableAttributes": [
        "state",
        "county",
        "countyFull",
        "eventType",
        "startDate",
        "endDate",
        "zip",
        "sourceType",
    ],
    "sortableAttributes": ["startDate", "name", "county"],
    "searchableAttributes": [
        "name",
        "venue",
        "city",
        "county",
        "eventType",
        "attendance",
    ],
    "typoTolerance": {
        "enabled": True,
        "minWordSizeForTypos": {"oneTypo": 5, "twoTypos": 9},
        "disableOnAttributes": ["zip", "startDate", "endDate"],
    },
    "faceting": {"maxValuesPerFacet": 500},
    "pagination": {"maxTotalHits": 10000},
    "rankingRules": [
        "words",
        "typo",
        "proximity",
        "attribute",
        "sort",
        "exactness",
    ],
}


class MeilisearchSync:
    def __init__(self, url: str, master_key: str):
        self._client = meilisearch.Client(url, master_key)
        self._index = self._client.index(INDEX_UID)

    def health(self) -> bool:
        try:
            self._client.health()
            return True
        except Exception as exc:
            logger.warning("Meilisearch health check failed: %s", exc)
            return False

    def configure_index(self) -> None:
        """Idempotently create the events index and apply settings."""
        try:
            task = self._client.create_index(INDEX_UID, {"primaryKey": PRIMARY_KEY})
            self._client.wait_for_task(task.task_uid, timeout_in_ms=15_000)
            logger.info("Created Meilisearch index '%s'", INDEX_UID)
        except meilisearch.errors.MeilisearchApiError as exc:
            code = getattr(exc, "code", "") or ""
            if (
                "already_exists" not in code.lower()
                and "already exists" not in str(exc).lower()
            ):
                raise
            logger.debug("Index '%s' already exists", INDEX_UID)
        except meilisearch.errors.MeilisearchTimeoutError:
            logger.warning("Timeout waiting for index creation — continuing")

        try:
            task = self._index.update_settings(_INDEX_SETTINGS)
            self._client.wait_for_task(task.task_uid, timeout_in_ms=30_000)
            logger.info("Applied index settings to '%s'", INDEX_UID)
        except meilisearch.errors.MeilisearchTimeoutError:
            logger.error(
                "Timeout waiting for index settings update — "
                "search filter/sort behavior may be incorrect until next run"
            )

    def clear_index(self) -> None:
        """Delete all documents from the index. Used before a full resync."""
        try:
            task = self._index.delete_all_documents()
            self._client.wait_for_task(task.task_uid, timeout_in_ms=30_000)
            logger.info("Cleared all documents from Meilisearch index '%s'", INDEX_UID)
        except meilisearch.errors.MeilisearchTimeoutError:
            logger.warning("Timeout waiting for index clear — proceeding anyway")
        except meilisearch.errors.MeilisearchApiError as exc:
            logger.error("Failed to clear Meilisearch index: %s", exc)

    def delete_documents(self, ids: list[str]) -> None:
        """Delete specific documents from Meilisearch by event_id."""
        if not ids:
            return
        try:
            task = self._index.delete_documents(ids)
            self._client.wait_for_task(task.task_uid, timeout_in_ms=30_000)
            logger.info("Deleted %d documents from Meilisearch", len(ids))
        except meilisearch.errors.MeilisearchTimeoutError:
            logger.warning("Timeout deleting %d Meilisearch docs — may retry next run", len(ids))
        except meilisearch.errors.MeilisearchApiError as exc:
            logger.error("Failed to delete %d docs from Meilisearch: %s", len(ids), exc)

    def sync_from_store(self, store) -> int:
        """Pull synced=0 rows from store, push to Meilisearch, mark synced."""
        unsynced = store.get_unsynced()
        if not unsynced:
            logger.info("No unsynced events to push")
            return 0

        docs = [_row_to_meili_doc(row) for row in unsynced]
        ids = [row["event_id"] for row in unsynced]
        synced_count = 0

        for i in range(0, len(docs), BATCH_SIZE):
            batch_docs = docs[i : i + BATCH_SIZE]
            batch_ids = ids[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = -(-len(docs) // BATCH_SIZE)
            try:
                task = self._index.add_documents(batch_docs, primary_key=PRIMARY_KEY)
                result = self._client.wait_for_task(task.task_uid, timeout_in_ms=60_000)
                task_status = getattr(result, "status", None) or (
                    result.get("status") if isinstance(result, dict) else None
                )
                if task_status != "succeeded":
                    logger.error(
                        "Meilisearch task failed for batch %d/%d (status=%s) — "
                        "skipping mark_synced, will retry next run",
                        batch_num,
                        total_batches,
                        task_status,
                    )
                    continue
                store.mark_synced(batch_ids)
                synced_count += len(batch_docs)
                logger.info(
                    "Pushed batch %d/%d (%d docs)",
                    batch_num,
                    total_batches,
                    len(batch_docs),
                )
            except meilisearch.errors.MeilisearchTimeoutError:
                logger.warning(
                    "Timeout on batch %d/%d — skipping mark_synced, will retry next run",
                    batch_num,
                    total_batches,
                )
            except meilisearch.errors.MeilisearchApiError as exc:
                logger.error(
                    "Meilisearch API error on batch %d/%d (%d docs): %s — "
                    "skipping, will retry next run",
                    batch_num,
                    total_batches,
                    len(batch_docs),
                    exc,
                )

        logger.info("Synced %d of %d events to Meilisearch", synced_count, len(docs))
        return synced_count


def _safe_json_load(value: str | None, event_id: str) -> list:
    try:
        return json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        logger.warning("Malformed JSON in row %s — using empty list", event_id)
        return []


def _row_to_meili_doc(row: dict) -> dict:
    return {
        "id": row["event_id"],
        "dedupKey": row["dedup_key"],
        "name": row["name"],
        "startDate": row["start_date"] or "",
        "endDate": row["end_date"] or "",
        "venue": row["venue"] or "",
        "city": row["city"] or "",
        "state": row["state"] or "",
        "county": row["county"] or "",
        "countyFull": row["county_full"] or "",
        "zip": row["zip"] or "",
        "eventType": row["event_type"] or "",
        "primaryUrl": row["primary_url"] or "",
        "sourceType": row["source_type"] or "",
        "sourceQueries": _safe_json_load(row["source_queries"], row["event_id"]),
        "sources": _safe_json_load(row["sources"], row["event_id"]),
        "attendance": row["attendance"] or "",
        "fetchedAt": row["fetched_at"] or "",
    }
