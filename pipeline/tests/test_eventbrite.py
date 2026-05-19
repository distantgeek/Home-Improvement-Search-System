"""Tests for pipeline.fetchers.eventbrite."""
import pytest
import responses as responses_lib

from pipeline.fetchers.eventbrite import (
    EVENTBRITE_SEARCH_URL,
    _normalize_eb_event,
    fetch_all,
)
from pipeline.models import EventItem


class TestNormalizeEbEvent:
    def test_returns_none_for_missing_name(self):
        result = _normalize_eb_event({"name": {"text": ""}}, "eventbrite:Maryland")
        assert result is None

    def test_extracts_structured_fields(self, eventbrite_payload):
        raw = eventbrite_payload["events"][0]
        item = _normalize_eb_event(raw, "eventbrite:DC")
        assert item is not None
        assert item.name == "DC Home & Design Show 2026"
        assert item.zip == "20001"
        assert item.state == "DC"
        assert item.city == "Washington"
        assert item.source_type == "eventbrite"

    def test_source_type_is_eventbrite(self, eventbrite_payload):
        raw = eventbrite_payload["events"][0]
        item = _normalize_eb_event(raw, "eventbrite:DC")
        assert item.source_type == "eventbrite"

    def test_page_score_is_2(self, eventbrite_payload):
        raw = eventbrite_payload["events"][0]
        item = _normalize_eb_event(raw, "eventbrite:DC")
        assert item.page_score == 2

    def test_zip_truncated_to_5_digits(self):
        raw = {
            "name": {"text": "Test Event"},
            "url": "https://eb.com/e/test",
            "start": {"local": "2026-06-01T10:00:00"},
            "end": {"local": "2026-06-03T18:00:00"},
            "venue": {
                "name": "Test Venue",
                "address": {
                    "city": "Rockville",
                    "region": "MD",
                    "postal_code": "20850-1234",  # +4 extension
                },
            },
        }
        item = _normalize_eb_event(raw, "eventbrite:MD")
        assert item.zip == "20850"

    def test_addr_full_built_for_enrichment(self, eventbrite_payload):
        raw = eventbrite_payload["events"][0]
        item = _normalize_eb_event(raw, "eventbrite:DC")
        assert item.addr_full != ""
        assert "20001" in item.addr_full


@responses_lib.activate
class TestFetchAll:
    def test_dry_run_returns_empty(self):
        result = fetch_all("api-key", dry_run=True)
        assert result == []
        assert len(responses_lib.calls) == 0

    def test_returns_empty_on_403(self):
        # Mock 403 for first state (MD) — should bail out gracefully
        responses_lib.add(
            responses_lib.GET,
            EVENTBRITE_SEARCH_URL,
            status=403,
        )
        result = fetch_all("bad-key")
        assert result == []

    def test_parses_event_items_from_response(self, eventbrite_payload):
        # Mock responses for all 6 states (MD, VA, PA, NJ, DE, DC)
        for _ in range(6):
            responses_lib.add(
                responses_lib.GET,
                EVENTBRITE_SEARCH_URL,
                json=eventbrite_payload,
                status=200,
            )
        result = fetch_all("valid-key")
        assert len(result) > 0
        assert all(isinstance(r, EventItem) for r in result)
        assert all(r.source_type == "eventbrite" for r in result)
