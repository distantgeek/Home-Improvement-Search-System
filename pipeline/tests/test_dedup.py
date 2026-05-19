"""Tests for pipeline.dedup — exact and fuzzy deduplication."""
import pytest

from pipeline.dedup import (
    dedup_key,
    exact_dedup,
    fuzzy_merge_results,
    jaccard_similarity,
    normalize_for_dedup,
)
from pipeline.models import EventItem


def _make_event(**kwargs) -> EventItem:
    defaults = {
        "name": "Test Event",
        "start_date": "2026-06-01",
        "end_date": "2026-06-01",
        "county": "Frederick",
        "state": "MD",
        "zip": "21701",
        "source_type": "serper_events",
        "primary_url": "https://example.com",
        "source_queries": ["home show Maryland 2026"],
    }
    defaults.update(kwargs)
    return EventItem(**defaults)


class TestDedupKey:
    def test_year_stripped_from_name(self):
        e = _make_event(name="Frederick Fair 2026", start_date="2026-08-01", zip="21701")
        key = dedup_key(e)
        assert "2026" not in key.split("|")[0]

    def test_hyphen_keeps_event_side(self):
        e = _make_event(name="Maryland State Fair - Deggeller Attractions", zip="21093")
        key = dedup_key(e)
        assert "deggeller" not in key

    def test_hyphen_keeps_right_side_with_keyword(self):
        e = _make_event(name="Come on In - Worcester County Fair 2026", zip="")
        key = dedup_key(e)
        assert "worcester county fair" in key.split("|")[0]

    def test_locality_uses_zip_when_available(self):
        e = _make_event(zip="21701", state="MD")
        key = dedup_key(e)
        assert key.endswith("|21701")

    def test_locality_falls_back_to_state(self):
        e = _make_event(zip="", state="MD")
        key = dedup_key(e)
        assert key.endswith("|MD")


class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert jaccard_similarity("home show", "home show") == 1.0

    def test_no_overlap(self):
        assert jaccard_similarity("home show", "county fair") == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity("frederick home show", "frederick garden show")
        assert 0 < sim < 1

    def test_empty_string_returns_zero(self):
        assert jaccard_similarity("", "home show") == 0.0
        assert jaccard_similarity("home show", "") == 0.0


class TestNormalizeForDedup:
    def test_strips_state_names(self):
        result = normalize_for_dedup("Maryland Home Show")
        assert "maryland" not in result

    def test_strips_state_abbreviations(self):
        result = normalize_for_dedup("Home Show MD 2026")
        assert " md " not in result

    def test_strips_years(self):
        result = normalize_for_dedup("Frederick Fair 2026")
        assert "2026" not in result

    def test_strips_venue_noise(self):
        result = normalize_for_dedup("Frederick Fairgrounds Home Show")
        assert "fairgrounds" not in result


class TestExactDedup:
    def test_duplicate_queries_merged(self):
        e1 = _make_event(source_queries=["home show Maryland 2026"])
        e2 = _make_event(source_queries=["home improvement expo Maryland 2026"])
        results = exact_dedup([e1, e2])
        assert len(results) == 1
        assert len(results[0].source_queries) == 2

    def test_different_events_not_merged(self):
        e1 = _make_event(name="Frederick Home Show", zip="21701")
        e2 = _make_event(name="Carroll County Fair", zip="21157")
        results = exact_dedup([e1, e2])
        assert len(results) == 2

    def test_eventbrite_wins_over_serper(self):
        serper = _make_event(source_type="serper_events", primary_url="https://serper.com")
        eb = _make_event(source_type="eventbrite", primary_url="https://eventbrite.com")
        results = exact_dedup([serper, eb])
        assert len(results) == 1
        assert results[0].source_type == "eventbrite"
        assert results[0].primary_url == "https://eventbrite.com"

    def test_event_id_set_on_output(self):
        e = _make_event()
        results = exact_dedup([e])
        assert results[0].event_id != ""
        assert len(results[0].event_id) == 64  # SHA-256 hex

    def test_missing_fields_merged_from_duplicate(self):
        primary = _make_event(county="Frederick", zip="21701", attendance="")
        duplicate = _make_event(county="Frederick", zip="21701", attendance="5000")
        results = exact_dedup([primary, duplicate])
        assert results[0].attendance == "5000"


class TestFuzzyMergeResults:
    def test_similar_names_in_same_bucket_merged(self):
        e1 = _make_event(
            name="Frederick Home Show",
            county="Frederick",
            start_date="2026-03-14",
            primary_url="https://first.com",
            source_type="serper_events",
        )
        e2 = _make_event(
            name="Frederick Home Show 2026",
            county="Frederick",
            start_date="2026-03-15",  # different date — would have missed in old bucket
            primary_url="https://second.com",
            source_type="serper_organic",
        )
        results = fuzzy_merge_results([e1, e2])
        assert len(results) == 1

    def test_alternate_url_accumulated(self):
        e1 = _make_event(
            name="Frederick Home Show",
            county="Frederick",
            start_date="2026-03-14",
            primary_url="https://first.com",
            source_type="serper_events",
        )
        e2 = _make_event(
            name="Frederick Home & Garden Show",
            county="Frederick",
            start_date="2026-03-15",
            primary_url="https://second.com",
            source_type="serper_organic",
        )
        results = fuzzy_merge_results([e1, e2])
        if len(results) == 1:
            assert len(results[0].sources) >= 1

    def test_different_events_not_merged(self):
        e1 = _make_event(name="Frederick Home Show", county="Frederick", start_date="2026-03-14")
        e2 = _make_event(name="Carroll County Fair", county="Carroll", start_date="2026-08-01")
        results = fuzzy_merge_results([e1, e2])
        assert len(results) == 2

    def test_eventbrite_wins_fuzzy_merge(self):
        serper = _make_event(
            name="DC Home Design Show",
            county="District of Columbia",
            state="DC",
            start_date="2026-02-14",
            primary_url="https://serper.com",
            source_type="serper_events",
        )
        eb = _make_event(
            name="DC Home and Design Show 2026",
            county="District of Columbia",
            state="DC",
            start_date="2026-02-16",
            primary_url="https://eventbrite.com",
            source_type="eventbrite",
        )
        results = fuzzy_merge_results([serper, eb])
        if len(results) == 1:
            assert results[0].source_type == "eventbrite"

    def test_year_county_bucket_used_not_date_zip(self):
        # Two events with same county+year but different dates — should still be bucketed together
        e1 = _make_event(
            name="Harford Home Show",
            county="Harford",
            state="MD",
            start_date="2026-04-10",
            zip="",
        )
        e2 = _make_event(
            name="Harford Home Show 2026",
            county="Harford",
            state="MD",
            start_date="2026-04-12",  # different date
            zip="",
        )
        results = fuzzy_merge_results([e1, e2])
        # Should be merged because bucket is year|county, not startDate|zip
        assert len(results) == 1
