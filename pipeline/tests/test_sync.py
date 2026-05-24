"""Tests for pipeline.sync — Meilisearch sync (mocked HTTP)."""

import json

import pytest
import responses as responses_lib

from pipeline.models import EventItem, make_event_id
from pipeline.store import Store
from pipeline.sync import MeilisearchSync, _row_to_meili_doc


def _make_stored_event(name: str = "Test Event") -> EventItem:
    key = f"{name.lower()}|2026|21701"
    return EventItem(
        event_id=make_event_id(key),
        dedup_key=key,
        name=name,
        start_date="2026-06-01",
        end_date="2026-06-03",
        state="MD",
        county="Frederick",
        county_full="Frederick County",
        zip="21701",
        event_type="Home Show",
        primary_url="https://example.com",
        source_type="serper_events",
        source_queries=["home show Maryland 2026"],
        fetched_at="2026-01-01T00:00:00+00:00",
    )


class TestRowToMeiliDoc:
    def test_camel_case_fields(self):
        row = {
            "event_id": "abc123",
            "dedup_key": "key",
            "name": "Test",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "venue": "V",
            "city": "C",
            "state": "MD",
            "county": "Frederick",
            "county_full": "Frederick County",
            "zip": "21701",
            "event_type": "Home Show",
            "primary_url": "https://example.com",
            "source_type": "serper_events",
            "source_queries": json.dumps(["q1"]),
            "sources": json.dumps([]),
            "attendance": "",
            "contact": "",
            "fetched_at": "2026-01-01T00:00:00+00:00",
        }
        doc = _row_to_meili_doc(row)
        assert doc["id"] == "abc123"
        assert doc["startDate"] == "2026-06-01"
        assert doc["countyFull"] == "Frederick County"
        assert doc["eventType"] == "Home Show"
        assert doc["primaryUrl"] == "https://example.com"
        assert doc["sourceType"] == "serper_events"
        assert doc["sourceQueries"] == ["q1"]
        assert isinstance(doc["sources"], list)

    def test_null_fields_become_empty_strings(self):
        row = {
            "event_id": "x",
            "dedup_key": "k",
            "name": "N",
            "start_date": None,
            "end_date": None,
            "venue": None,
            "city": None,
            "state": None,
            "county": None,
            "county_full": None,
            "zip": None,
            "event_type": None,
            "primary_url": None,
            "source_type": None,
            "source_queries": None,
            "sources": None,
            "attendance": None,
            "contact": None,
            "fetched_at": None,
        }
        doc = _row_to_meili_doc(row)
        assert doc["startDate"] == ""
        assert doc["county"] == ""
        assert doc["sourceQueries"] == []


class TestMeilisearchSync:
    MEILI_URL = "http://meili-test:7700"
    MASTER_KEY = "test-master-key"

    def _mock_health(self):
        responses_lib.add(
            responses_lib.GET,
            f"{self.MEILI_URL}/health",
            json={"status": "available"},
            status=200,
        )

    def _mock_create_index(self):
        responses_lib.add(
            responses_lib.POST,
            f"{self.MEILI_URL}/indexes",
            json={
                "taskUid": 1,
                "indexUid": "events",
                "status": "enqueued",
                "type": "indexCreation",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=202,
        )
        responses_lib.add(
            responses_lib.GET,
            f"{self.MEILI_URL}/tasks/1",
            json={
                "uid": 1,
                "status": "succeeded",
                "type": "indexCreation",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=200,
        )

    def _mock_update_settings(self):
        responses_lib.add(
            responses_lib.PATCH,
            f"{self.MEILI_URL}/indexes/events/settings",
            json={
                "taskUid": 2,
                "indexUid": "events",
                "status": "enqueued",
                "type": "settingsUpdate",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=202,
        )
        responses_lib.add(
            responses_lib.GET,
            f"{self.MEILI_URL}/tasks/2",
            json={
                "uid": 2,
                "status": "succeeded",
                "type": "settingsUpdate",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=200,
        )

    def _mock_add_documents(self):
        responses_lib.add(
            responses_lib.POST,
            f"{self.MEILI_URL}/indexes/events/documents",
            json={
                "taskUid": 3,
                "indexUid": "events",
                "status": "enqueued",
                "type": "documentAdditionOrUpdate",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=202,
        )
        responses_lib.add(
            responses_lib.GET,
            f"{self.MEILI_URL}/tasks/3",
            json={
                "uid": 3,
                "status": "succeeded",
                "type": "documentAdditionOrUpdate",
                "enqueuedAt": "2026-01-01T00:00:00.000Z",
            },
            status=200,
        )

    @responses_lib.activate
    def test_health_returns_true_when_available(self):
        self._mock_health()
        syncer = MeilisearchSync(self.MEILI_URL, self.MASTER_KEY)
        assert syncer.health() is True

    @responses_lib.activate
    def test_sync_from_store_pushes_unsynced_events(self, tmp_db):
        self._mock_create_index()
        self._mock_update_settings()
        self._mock_add_documents()

        store = Store(tmp_db)
        event = _make_stored_event()
        store.upsert_events([event])

        syncer = MeilisearchSync(self.MEILI_URL, self.MASTER_KEY)
        syncer.configure_index()
        synced = syncer.sync_from_store(store)

        assert synced == 1
        assert store.get_unsynced() == []
        store.close()

    @responses_lib.activate
    def test_sync_from_store_skips_when_nothing_unsynced(self, tmp_db):
        store = Store(tmp_db)
        syncer = MeilisearchSync(self.MEILI_URL, self.MASTER_KEY)
        synced = syncer.sync_from_store(store)
        assert synced == 0
        store.close()
