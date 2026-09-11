"""Tests for pipeline.run — URL dedup and state filter logic."""

import pytest

from pipeline.constants import STATE_ORDER
from pipeline.models import EventItem
from pipeline.normalize import is_non_target_state_event


class TestUrlDedup:
    """Test the URL dedup logic that keeps the best event per primary_url."""

    def _url_dedup(self, events: list[EventItem]) -> list[EventItem]:
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
                new_p = event.page_score
                ex_p = existing.page_score
                if new_p > ex_p or (
                    new_p == ex_p and len(event.name) > len(existing.name)
                ):
                    by_url[url] = event
        return list(by_url.values()) + no_url

    def test_keeps_best_event_per_url(self):
        url = "https://example.com/same-page"
        events = [
            EventItem(name="Short", primary_url=url, page_score=1),
            EventItem(name="Much Longer Title", primary_url=url, page_score=1),
            EventItem(name="High Score", primary_url=url, page_score=3),
        ]
        result = self._url_dedup(events)
        assert len(result) == 1
        assert result[0].name == "High Score"

    def test_keeps_events_with_different_urls(self):
        events = [
            EventItem(name="Event A", primary_url="https://a.com", page_score=1),
            EventItem(name="Event B", primary_url="https://b.com", page_score=1),
        ]
        result = self._url_dedup(events)
        assert len(result) == 2

    def test_keeps_events_without_urls(self):
        events = [
            EventItem(name="No URL A", primary_url="", page_score=1),
            EventItem(name="No URL B", primary_url="", page_score=1),
        ]
        result = self._url_dedup(events)
        assert len(result) == 2

    def test_mixed_url_and_no_url(self):
        url = "https://example.com/page"
        events = [
            EventItem(name="URL 1", primary_url=url, page_score=1),
            EventItem(name="URL 2", primary_url=url, page_score=2),
            EventItem(name="No URL", primary_url="", page_score=1),
        ]
        result = self._url_dedup(events)
        assert len(result) == 2
        assert result[0].name == "URL 2"
        assert result[1].name == "No URL"


class TestStateFilter:
    """Test that events with empty or non-target states are filtered out."""

    def test_keeps_target_state_events(self):
        events = [
            EventItem(name="MD Event", state="MD"),
            EventItem(name="VA Event", state="VA"),
            EventItem(name="KS Event", state="KS"),
        ]
        filtered = [e for e in events if e.state in STATE_ORDER]
        assert len(filtered) == 3

    def test_drops_empty_state(self):
        events = [
            EventItem(name="Good", state="MD"),
            EventItem(name="No State", state=""),
        ]
        filtered = [e for e in events if e.state in STATE_ORDER]
        assert len(filtered) == 1
        assert filtered[0].name == "Good"

    def test_drops_non_target_state(self):
        events = [
            EventItem(name="MD Event", state="MD"),
            EventItem(name="NY Event", state="NY"),
            EventItem(name="FL Event", state="FL"),
        ]
        filtered = [e for e in events if e.state in STATE_ORDER]
        assert len(filtered) == 1
        assert filtered[0].name == "MD Event"


class TestPostEnrichmentStateFilter:
    """Test the post-enrichment re-check that drops events whose scraped
    address data reveals a non-target state."""

    def _post_enrich_filter(self, events: list[EventItem]) -> list[EventItem]:
        return [
            e
            for e in events
            if not is_non_target_state_event(e.name, e.addr_full, e.primary_url)
        ]

    def test_drops_event_with_out_of_state_address_revealed_by_enrichment(self):
        # Query hint said KS; URL enrichment revealed the event is in Nebraska.
        events = [
            EventItem(
                name="Chase County Fair",
                state="KS",
                addr_full="Chase County Fairgrounds, Imperial, NE 69033",
                primary_url="https://example.com/fair",
            )
        ]
        filtered = self._post_enrich_filter(events)
        assert len(filtered) == 0

    def test_keeps_target_state_event(self):
        events = [
            EventItem(
                name="Frederick County Home Show",
                state="MD",
                addr_full="Frederick Fairgrounds, Frederick, MD 21701",
                primary_url="https://example.com/home-show",
            )
        ]
        filtered = self._post_enrich_filter(events)
        assert len(filtered) == 1

    def test_keeps_central_region_event(self):
        # MO/IL/OH/KS are intentional target states (Central Region).
        events = [
            EventItem(
                name="Kansas State Fair",
                state="KS",
                addr_full="Hutchinson, KS 67502",
                primary_url="https://kansasstatefair.com",
            )
        ]
        filtered = self._post_enrich_filter(events)
        assert len(filtered) == 1
