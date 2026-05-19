"""Tests for pipeline.fetchers.eventbrite_enrich."""
import pytest
import responses as responses_lib

from pipeline.fetchers.eventbrite_enrich import (
    _apply_enrichment,
    _validate_response,
    enrich_from_urls,
    extract_eventbrite_id,
)
from pipeline.models import EventItem

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_event(
    name: str = "Frederick County Home Show",
    primary_url: str = "https://www.eventbrite.com/e/frederick-county-home-show-tickets-123456789",
    sources: list | None = None,
) -> EventItem:
    return EventItem(name=name, primary_url=primary_url, sources=sources or [])


def _api_response(
    event_id: str = "123456789",
    name: str = "Frederick County Home Show",
    status: str = "live",
    zip_code: str = "21702",
    city: str = "Frederick",
    region: str = "MD",
    venue_name: str = "Frederick Fairgrounds",
    address_1: str = "797 E Patrick St",
) -> dict:
    return {
        "id": event_id,
        "name": {"text": name},
        "status": status,
        "venue": {
            "name": venue_name,
            "address": {
                "address_1": address_1,
                "city": city,
                "region": region,
                "postal_code": zip_code,
            },
        },
    }


# ── extract_eventbrite_id ─────────────────────────────────────────────────────


class TestExtractEventbriteId:
    def test_standard_slug_url(self):
        url = "https://www.eventbrite.com/e/home-show-tickets-123456789"
        assert extract_eventbrite_id(url) == "123456789"

    def test_bare_id_url(self):
        url = "https://www.eventbrite.com/e/123456789"
        assert extract_eventbrite_id(url) == "123456789"

    def test_url_with_query_string(self):
        url = "https://www.eventbrite.com/e/home-show-tickets-123456789?aff=ebdssbonlinesearch"
        assert extract_eventbrite_id(url) == "123456789"

    def test_non_www_host(self):
        url = "https://eventbrite.com/e/home-show-tickets-123456789"
        assert extract_eventbrite_id(url) == "123456789"

    def test_rejects_http_scheme(self):
        url = "http://www.eventbrite.com/e/home-show-tickets-123456789"
        assert extract_eventbrite_id(url) is None

    def test_rejects_wrong_host(self):
        url = "https://www.eventbrite.co.uk/e/home-show-tickets-123456789"
        assert extract_eventbrite_id(url) is None

    def test_rejects_lookalike_host(self):
        url = "https://eventbrite.com.malicious.example/e/123456789"
        assert extract_eventbrite_id(url) is None

    def test_rejects_non_event_path(self):
        url = "https://www.eventbrite.com/o/organizer-name-12345678"
        assert extract_eventbrite_id(url) is None

    def test_rejects_id_too_short(self):
        url = "https://www.eventbrite.com/e/home-show-1234"
        assert extract_eventbrite_id(url) is None

    def test_rejects_id_too_long(self):
        url = "https://www.eventbrite.com/e/home-show-123456789012345678901"
        assert extract_eventbrite_id(url) is None

    def test_rejects_empty_string(self):
        assert extract_eventbrite_id("") is None

    def test_rejects_non_eventbrite_url(self):
        assert extract_eventbrite_id("https://www.google.com/e/123456789") is None

    def test_long_valid_id(self):
        url = "https://www.eventbrite.com/e/home-expo-tickets-98765432109876"
        assert extract_eventbrite_id(url) == "98765432109876"


# ── _validate_response ────────────────────────────────────────────────────────


class TestValidateResponse:
    def test_valid_response_passes(self):
        event = _make_event()
        raw = _api_response()
        assert _validate_response(raw, "123456789", event) is True

    def test_rejects_id_mismatch(self):
        event = _make_event()
        raw = _api_response(event_id="999999999")
        assert _validate_response(raw, "123456789", event) is False

    def test_rejects_cancelled_event(self):
        event = _make_event()
        raw = _api_response(status="cancelled")
        assert _validate_response(raw, "123456789", event) is False

    def test_rejects_name_with_no_token_overlap(self):
        event = _make_event(name="Blueberry Picking Festival")
        raw = _api_response(name="Car Show and Auto Expo")
        assert _validate_response(raw, "123456789", event) is False

    def test_accepts_partial_name_overlap(self):
        # "Frederick" appears in both — one significant token is enough
        event = _make_event(name="Frederick Home Show")
        raw = _api_response(name="The 45th Annual Frederick County Home and Garden Show 2026")
        assert _validate_response(raw, "123456789", event) is True

    def test_accepts_when_both_token_sets_empty(self):
        # Very short/generic names produce no tokens — ID match is sufficient,
        # so we accept rather than reject on a vacuous intersection check.
        event = _make_event(name="Home Show")
        raw = _api_response(name="Home Show")
        assert _validate_response(raw, "123456789", event) is True

    def test_rejects_when_tokens_exist_but_no_overlap(self):
        # Both sides have tokens but nothing in common — genuine mismatch
        event = _make_event(name="Blueberry Picking Festival Annapolis")
        raw = _api_response(name="Automobile Restoration Convention Richmond")
        assert _validate_response(raw, "123456789", event) is False

    def test_rejects_missing_id_field(self):
        event = _make_event()
        raw = {"name": {"text": "Frederick County Home Show"}, "status": "live"}
        assert _validate_response(raw, "123456789", event) is False


# ── _apply_enrichment ─────────────────────────────────────────────────────────


class TestApplyEnrichment:
    def test_updates_address_fields(self):
        event = _make_event()
        _apply_enrichment(event, _api_response())
        assert event.zip == "21702"
        assert event.city == "Frederick"
        assert event.state == "MD"
        assert event.venue == "Frederick Fairgrounds"

    def test_truncates_zip_plus4(self):
        event = _make_event()
        raw = _api_response(zip_code="21702-1234")
        _apply_enrichment(event, raw)
        assert event.zip == "21702"

    def test_rebuilds_addr_full(self):
        event = _make_event()
        _apply_enrichment(event, _api_response())
        assert "21702" in event.addr_full
        assert "Frederick" in event.addr_full
        assert "Frederick Fairgrounds" in event.addr_full

    def test_does_not_overwrite_with_empty(self):
        event = _make_event()
        event.zip = "21702"
        event.city = "Frederick"
        raw = _api_response(zip_code="", city="")
        _apply_enrichment(event, raw)
        assert event.zip == "21702"
        assert event.city == "Frederick"

    def test_addr_full_empty_when_no_data(self):
        event = _make_event()
        _apply_enrichment(event, {"id": "123456789", "status": "live", "name": {"text": "Test"}})
        assert event.addr_full == ""


# ── enrich_from_urls ──────────────────────────────────────────────────────────


def _register(event_id: str, payload: dict, status: int = 200) -> None:
    responses_lib.add(
        responses_lib.GET,
        f"https://www.eventbriteapi.com/v3/events/{event_id}/",
        json=payload,
        status=status,
    )


class TestEnrichFromUrls:
    @responses_lib.activate
    def test_enriches_valid_eventbrite_event(self):
        event = _make_event()
        _register("123456789", _api_response())
        count = enrich_from_urls([event], "test-key")
        assert count == 1
        assert event.zip == "21702"
        assert event.city == "Frederick"

    def test_skips_non_eventbrite_url(self):
        event = EventItem(
            name="Home Show",
            primary_url="https://www.homeshowexpo.com/tickets/123456789",
        )
        count = enrich_from_urls([event], "test-key")
        assert count == 0

    @responses_lib.activate
    def test_deduplicates_same_event_id(self):
        """Two events pointing at the same Eventbrite ID → one API call."""
        e1 = _make_event(name="Frederick County Home Show A")
        e2 = _make_event(name="Frederick County Home Show B")
        _register("123456789", _api_response())
        enrich_from_urls([e1, e2], "test-key")
        assert len(responses_lib.calls) == 1

    @responses_lib.activate
    def test_skips_404(self):
        event = _make_event()
        _register("123456789", {}, status=404)
        count = enrich_from_urls([event], "test-key")
        assert count == 0

    @responses_lib.activate
    def test_skips_403(self):
        event = _make_event()
        _register("123456789", {}, status=403)
        count = enrich_from_urls([event], "test-key")
        assert count == 0

    @responses_lib.activate
    def test_skips_401(self):
        # Free-tier tokens lack retrieval scope — should be silent, not a warning
        event = _make_event()
        _register("123456789", {}, status=401)
        count = enrich_from_urls([event], "test-key")
        assert count == 0

    @responses_lib.activate
    def test_skips_on_name_mismatch(self):
        event = _make_event(name="Blueberry Picking Festival")
        _register("123456789", _api_response(name="Car Show and Auto Expo"))
        count = enrich_from_urls([event], "test-key")
        assert count == 0
        assert event.zip == ""
        assert event.city == ""

    @responses_lib.activate
    def test_picks_up_eventbrite_url_from_sources(self):
        """Primary URL is not Eventbrite; alternate source URL is."""
        event = EventItem(
            name="Frederick County Home Show",
            primary_url="https://www.homeshowexpo.com/",
            sources=[
                {
                    "url": "https://www.eventbrite.com/e/frederick-home-show-tickets-123456789",
                    "sourceType": "serper_events",
                }
            ],
        )
        _register("123456789", _api_response())
        count = enrich_from_urls([event], "test-key")
        assert count == 1
        assert event.zip == "21702"

    def test_returns_zero_for_empty_list(self):
        assert enrich_from_urls([], "test-key") == 0
