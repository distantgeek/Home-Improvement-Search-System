"""Tests for pipeline.store — SQLite persistence."""
import pytest

from pipeline.models import EventItem, make_event_id
from pipeline.store import Store


def _make_event(name: str = "Frederick Home Show", event_id: str = "") -> EventItem:
    key = f"{name.lower()}|2026|21701"
    eid = event_id or make_event_id(key)
    return EventItem(
        event_id=eid,
        dedup_key=key,
        name=name,
        start_date="2026-03-14",
        end_date="2026-03-16",
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


class TestStore:
    def test_upsert_inserts_new_event(self, tmp_db):
        store = Store(tmp_db)
        n = store.upsert_events([_make_event()])
        assert n == 1
        assert store.count() == 1
        store.close()

    def test_upsert_is_idempotent(self, tmp_db):
        store = Store(tmp_db)
        event = _make_event()
        store.upsert_events([event])
        store.upsert_events([event])
        assert store.count() == 1
        store.close()

    def test_upsert_updates_existing_record(self, tmp_db):
        store = Store(tmp_db)
        event = _make_event()
        store.upsert_events([event])

        updated = _make_event()
        updated.venue = "New Venue Name"
        store.upsert_events([updated])

        rows = store.get_unsynced()
        assert rows[0]["venue"] == "New Venue Name"
        store.close()

    def test_upsert_marks_synced_zero(self, tmp_db):
        store = Store(tmp_db)
        store.upsert_events([_make_event()])
        rows = store.get_unsynced()
        assert len(rows) == 1
        store.close()

    def test_mark_synced_removes_from_unsynced(self, tmp_db):
        store = Store(tmp_db)
        event = _make_event()
        store.upsert_events([event])
        store.mark_synced([event.event_id])
        assert store.get_unsynced() == []
        store.close()

    def test_re_upsert_after_sync_marks_unsynced_again(self, tmp_db):
        store = Store(tmp_db)
        event = _make_event()
        store.upsert_events([event])
        store.mark_synced([event.event_id])
        assert store.get_unsynced() == []

        # Re-upsert should reset synced to 0
        store.upsert_events([event])
        assert len(store.get_unsynced()) == 1
        store.close()

    def test_purge_expired_deletes_old_events(self, tmp_db):
        store = Store(tmp_db)
        old = _make_event("Old Event")
        old.end_date = "2020-01-01"
        store.upsert_events([old])
        deleted = store.purge_expired(days=30)
        assert len(deleted) == 1
        assert store.count() == 0
        store.close()

    def test_purge_expired_returns_event_ids(self, tmp_db):
        store = Store(tmp_db)
        old = _make_event("Old Event")
        old.end_date = "2020-01-01"
        store.upsert_events([old])
        deleted = store.purge_expired(days=30)
        assert isinstance(deleted, list)
        assert len(deleted) == 1
        assert isinstance(deleted[0], str)
        store.close()

    def test_purge_expired_keeps_recent_events(self, tmp_db):
        store = Store(tmp_db)
        recent = _make_event("Recent Event")
        recent.end_date = "2099-12-31"
        store.upsert_events([recent])
        deleted = store.purge_expired(days=30)
        assert len(deleted) == 0
        assert store.count() == 1
        store.close()

    def test_purge_skips_events_with_empty_end_date(self, tmp_db):
        store = Store(tmp_db)
        no_date = _make_event("No Date Event")
        no_date.end_date = ""
        store.upsert_events([no_date])
        deleted = store.purge_expired(days=30)
        assert len(deleted) == 0
        store.close()

    def test_url_dedup_cleanup_removes_stale_duplicate(self, tmp_db):
        store = Store(tmp_db)
        # Two events, same URL, different event_ids (cross-run accumulation)
        winner = _make_event("Frederick County Fair 2026")
        winner.primary_url = "https://frederickcountyfair.com/"
        stale = _make_event("Frederick Co Fair 2026")
        stale.primary_url = "https://frederickcountyfair.com/"
        store.upsert_events([winner, stale])
        assert store.count() == 2

        deleted = store.url_dedup_cleanup({winner.primary_url: winner.event_id})
        assert len(deleted) == 1
        assert deleted[0] == stale.event_id
        assert store.count() == 1
        store.close()

    def test_url_dedup_cleanup_skips_empty_urls(self, tmp_db):
        store = Store(tmp_db)
        e = _make_event("No URL Event")
        e.primary_url = ""
        store.upsert_events([e])
        deleted = store.url_dedup_cleanup({"": e.event_id})
        assert deleted == []
        store.close()

    def test_empty_upsert_returns_zero(self, tmp_db):
        store = Store(tmp_db)
        assert store.upsert_events([]) == 0
        store.close()
