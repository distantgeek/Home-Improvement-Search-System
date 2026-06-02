"""Tests for pipeline.normalize — ported from index.html parseDates / inferEventType."""
import pytest

from pipeline.normalize import (
    infer_event_type,
    normalize_event,
    organics_to_events,
    parse_dates,
)


class TestParseDates:
    def test_returns_empty_on_none(self):
        assert parse_dates(None) == ("", "")

    def test_returns_empty_on_empty_string(self):
        assert parse_dates("") == ("", "")

    def test_plain_date_no_range(self):
        start, end = parse_dates("Apr 18, 2026")
        assert start == "2026-04-18"
        assert end == "2026-04-18"

    def test_weekday_prefix(self):
        start, end = parse_dates("Sat, Apr 18, 2026")
        assert start == "2026-04-18"
        assert end == "2026-04-18"

    def test_range_same_month(self):
        start, end = parse_dates("Apr 18 – 19, 2026")
        assert start == "2026-04-18"
        assert end == "2026-04-19"

    def test_range_cross_month(self):
        start, end = parse_dates("Aug 27 – Sep 7, 2026")
        assert start == "2026-08-27"
        assert end == "2026-09-07"

    def test_dict_with_when_and_start(self):
        start, end = parse_dates({"startDate": "Mar 14, 2026", "when": "Mar 14 – 16, 2026"})
        assert start == "2026-03-14"
        assert end == "2026-03-16"

    def test_dict_only_start_date(self):
        start, end = parse_dates({"startDate": "Mar 14, 2026"})
        assert start == "2026-03-14"
        assert end == "2026-03-14"

    def test_iso_format_from_eventbrite(self):
        start, end = parse_dates("2026-04-18T10:00:00")
        assert start == "2026-04-18"
        assert end == "2026-04-18"

    def test_year_borrowed_from_range_string(self):
        # "Mar 14 – 16" has no year in the start portion — borrow from "Mar 14 – 16, 2026"
        start, end = parse_dates("Mar 14 – 16, 2026")
        assert start == "2026-03-14"
        assert end == "2026-03-16"

    def test_unrecognised_string_returns_empty(self):
        assert parse_dates("not a date") == ("", "")

    def test_end_before_start_ignored(self):
        # If range parsing produces end < start, fall back to start == end
        start, end = parse_dates("Apr 19 – 18, 2026")
        assert start == end


class TestInferEventType:
    def test_state_fair(self):
        assert infer_event_type("state fair Maryland 2026", "") == "State Fair"

    def test_county_fair(self):
        assert infer_event_type("Frederick County fair Maryland 2026", "") == "County Fair"

    def test_fall_festival_keywords(self):
        for keyword in ("harvest festival", "fall festival", "pumpkin festival", "oktoberfest"):
            assert infer_event_type(keyword, "") == "Fall Festival"

    def test_food_festival(self):
        assert infer_event_type("wine festival Virginia 2026", "") == "Food Festival"

    def test_community_festival(self):
        assert infer_event_type("community festival", "") == "Community Festival"

    def test_home_and_garden(self):
        assert infer_event_type("home and garden show", "") == "Home & Garden"

    def test_art_craft(self):
        assert infer_event_type("craft show Maryland", "") == "Art & Craft"

    def test_default_home_show(self):
        assert infer_event_type("home improvement expo", "") == "Home Show"

    def test_title_used_when_query_ambiguous(self):
        assert infer_event_type("", "Frederick County Fair") == "County Fair"


class TestOrganicsToEvents:
    def test_filters_skip_domains(self, serper_organic_payload):
        organics = serper_organic_payload["organic"]
        results = organics_to_events(organics)
        urls = [r["link"] for r in results]
        assert not any("wikipedia.org" in u for u in urls)

    def test_filters_non_event_organics(self, serper_organic_payload):
        organics = serper_organic_payload["organic"]
        results = organics_to_events(organics)
        # Only home show / event organic results kept
        assert len(results) >= 1

    def test_title_cleanup_removes_site_suffix(self):
        organics = [
            {
                "title": "Carroll County Home Show 2026 | Carroll County Agricultural Center",
                "snippet": "Annual home show, March 7-9 2026, Westminster MD",
                "link": "https://example.com/home-show",
            }
        ]
        results = organics_to_events(organics)
        assert len(results) == 1
        assert "|" not in results[0]["title"]

    def test_sets_source_type_serper_organic(self):
        organics = [
            {
                "title": "Virginia Home Improvement Expo 2026",
                "snippet": "Home show, Feb 20-22 2026",
                "link": "https://example.com/va-expo",
            }
        ]
        results = organics_to_events(organics)
        assert all(r.get("_source_type") == "serper_organic" for r in results)

    def test_attendance_extraction(self):
        organics = [
            {
                "title": "Big County Fair",
                "snippet": "county fair with over 50,000 attendees every year",
                "link": "https://example.com/fair",
            }
        ]
        results = organics_to_events(organics)
        assert results[0]["attendance"] == "50,000"

    def test_rejects_short_non_event_titles(self):
        """Pages titled 'SPONSORS' or similar nav labels should be rejected."""
        for bad_title in ("SPONSORS", "CONTACT US", "ANIMAL EXHIBITS", "INDOOR EXHIBITS", "Home"):
            organics = [
                {
                    "title": bad_title,
                    "snippet": "Visit the Talbot County Fair for fun and food",
                    "link": "https://example.com/sponsors",
                }
            ]
            results = organics_to_events(organics)
            assert results == [], f"Should reject title: {bad_title}"

    def test_rejects_subsite_suffix_titles(self):
        """Pages like 'X - FairEntry.com' are registration sub-pages, not events."""
        organics = [
            {
                "title": "Talbot County Fair - FairEntry.com",
                "snippet": "Register for the Talbot County Fair online",
                "link": "https://fairentry.com/event/123",
            }
        ]
        results = organics_to_events(organics)
        assert results == []

    def test_rejects_aggregator_titles(self):
        """Aggregator listing pages like 'Discover fairs...' should be rejected."""
        organics = [
            {
                "title": "Discover fairs, festivals, and events in MARYLAND",
                "snippet": "Find upcoming county fairs and festivals across Maryland",
                "link": "https://example.com/events/md",
            }
        ]
        results = organics_to_events(organics)
        assert results == []

    def test_rejects_titles_without_event_keywords(self):
        """Even if title+snippet matches, the title itself must contain event keywords."""
        organics = [
            {
                "title": "About Our Agricultural Education Programs",
                "snippet": "Includes the annual county fair, craft show, and food festival events",
                "link": "https://example.com/about",
            }
        ]
        results = organics_to_events(organics)
        assert results == []

    def test_accepts_short_event_title(self):
        """Short event titles should not be rejected by length alone —
        they are case-by-case and often legitimate (e.g. 'Oktoberfest')."""
        organics = [
            {
                "title": "Oktoberfest 2026",
                "snippet": "Annual oktoberfest celebration with food and music",
                "link": "https://example.com/oktoberfest",
            }
        ]
        results = organics_to_events(organics)
        assert len(results) == 1

    def test_accepts_legitimate_event_title(self):
        """A normal event title should still pass all guards."""
        organics = [
            {
                "title": "Talbot County Fair",
                "snippet": "Annual Talbot County Fair with rides, food, and exhibits",
                "link": "https://facebook.com/talbotcountyfair",
            }
        ]
        results = organics_to_events(organics)
        assert len(results) == 1
        assert results[0]["title"] == "Talbot County Fair"


class TestNormalizeEvent:
    def test_returns_none_for_empty_title(self):
        assert normalize_event({"title": "", "link": ""}, "home show MD", "MD") is None

    def test_extracts_zip_from_address_string(self):
        evt = {
            "title": "Frederick Home Show",
            "date": "Mar 14, 2026",
            "address": "Frederick Fairgrounds, 797 E Patrick St, Frederick, MD 21701",
            "link": "https://example.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "home show Maryland", "MD")
        assert item is not None
        assert item.zip == "21701"

    def test_address_list_sets_venue(self):
        evt = {
            "title": "Carroll Fair",
            "date": "Aug 1, 2026",
            "address": ["Carroll County Ag Center", "706 Agricultural Center Dr, Westminster, MD 21157"],
            "link": "https://example.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "county fair Maryland", "MD")
        assert item is not None
        assert item.venue == "Carroll County Ag Center"
        assert item.zip == "21157"

    def test_source_type_preserved(self):
        evt = {
            "title": "Some Show",
            "date": "Apr 1, 2026",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "query", "VA")
        assert item.source_type == "serper_organic"

    def test_state_set_from_search_state(self):
        evt = {
            "title": "Some Event",
            "date": "May 1, 2026",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "query", "VA")
        assert item.state == "VA"
