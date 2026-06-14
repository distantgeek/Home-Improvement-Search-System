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
        start, end = parse_dates(
            {"startDate": "Mar 14, 2026", "when": "Mar 14 – 16, 2026"}
        )
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
        assert (
            infer_event_type("Frederick County fair Maryland 2026", "") == "County Fair"
        )

    def test_fall_festival_keywords(self):
        for keyword in (
            "harvest festival",
            "fall festival",
            "pumpkin festival",
            "oktoberfest",
        ):
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

    def test_filters_noise_aggregator_domains(self):
        noise_urls = [
            "https://www.yelp.com/events/frederick-home-show",
            "https://reddit.com/r/Maryland/comments/fair2026",
            "https://www.seatgeek.com/home-show-tickets",
            "https://bandsintown.com/e/county-fair",
            "https://www.etix.com/ticket/v/fair-2026",
            "https://10times.com/home-expo-md",
            "https://www.mapquest.com/events/123",
            "https://open.spotify.com/show/county-fair",
        ]
        organics = [
            {
                "title": f"Frederick County Home Show 2026 - {domain}",
                "snippet": "Annual home show in Frederick County, MD, July 2026",
                "link": url,
            }
            for domain, url in [
                (u.split("/")[2], u) for u in noise_urls
            ]
        ]
        results = organics_to_events(organics)
        assert results == [], f"Expected all noise domains filtered, got: {results}"

    def test_facebook_not_filtered_by_skip_domain(self):
        # Facebook stays in the pipeline (enrichment is skipped, not ingestion).
        organics = [
            {
                "title": "Frederick County Home Show 2026",
                "snippet": "Annual home show in Frederick County, MD · July 5-7, 2026",
                "link": "https://www.facebook.com/events/123456789",
            }
        ]
        results = organics_to_events(organics)
        assert len(results) == 1, "Facebook events should pass through to the pipeline"

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
        for bad_title in (
            "SPONSORS",
            "CONTACT US",
            "ANIMAL EXHIBITS",
            "INDOOR EXHIBITS",
            "Home",
        ):
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
            "address": [
                "Carroll County Ag Center",
                "706 Agricultural Center Dr, Westminster, MD 21157",
            ],
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

    def test_state_extracted_from_address_abbreviation(self):
        evt = {
            "title": "Delaware State Fair",
            "date": "Jul 1, 2026",
            "address": "Harrington, DE 19952",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "state fair Delaware", None)
        assert item is not None
        assert item.state == "DE"

    def test_state_extracted_from_address_full_name(self):
        evt = {
            "title": "Maryland Home Show",
            "date": "Mar 1, 2026",
            "address": "Maryland State Fairgrounds, Timonium",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "home show Maryland", None)
        assert item is not None
        assert item.state == "MD"

    def test_state_from_search_state_takes_priority_over_address(self):
        evt = {
            "title": "Border Event",
            "date": "Jun 1, 2026",
            "address": "Wilmington, DE 19801",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "home show Maryland", "MD")
        assert item is not None
        assert item.state == "MD"

    def test_pdf_url_skipped_in_organics(self):
        organics = [
            {
                "title": "2026 County Fair Dates",
                "snippet": "County fair schedule for Kansas 2026",
                "link": "https://extension.k-state.edu/about/statewide-locations/2026%20County%20Fair%20Dates.pdf",
            }
        ]
        results = organics_to_events(organics)
        assert results == []

    def test_duplicate_url_skipped_in_organics(self):
        url = "https://example.com/same-event-page"
        organics = [
            {
                "title": "County Fair Event A",
                "snippet": "county fair schedule 2026",
                "link": url,
            },
            {
                "title": "County Fair Event B",
                "snippet": "another county fair 2026",
                "link": url,
            },
        ]
        results = organics_to_events(organics)
        assert len(results) == 1


class TestNonTargetStateGuard:
    """Test that events mentioning non-target states are rejected."""

    def test_rejects_nebraska_in_title(self):
        evt = {
            "title": "Chase County Fair - Nebraska Association of Fair Managers",
            "date": "Jul 1, 2026",
            "address": "",
            "link": "https://nebraskafairs.org/fairs.php?fairid=14",
            "_source_type": "serper_organic",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None

    def test_rejects_nebraska_in_url(self):
        evt = {
            "title": "Cheyenne County Fair - Nebraska Extension",
            "date": "Jul 1, 2026",
            "address": "",
            "link": "https://extension.unl.edu/statewide/cheyenne/fair",
            "_source_type": "serper_organic",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None

    def test_rejects_colorado_in_title(self):
        evt = {
            "title": "Kiowa County Fair Board - Colorado",
            "date": "Jul 1, 2026",
            "address": "",
            "link": "https://kiowacounty.colorado.gov/fair",
            "_source_type": "serper_events",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None

    def test_rejects_iowa_in_url(self):
        evt = {
            "title": "Clay County Fair 2026",
            "date": "Sep 1, 2026",
            "address": "",
            "link": "https://governor.iowa.gov/events/clay-county-fair",
            "_source_type": "serper_events",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None

    def test_rejects_non_target_state_abbreviation_in_address(self):
        evt = {
            "title": "County Fair",
            "date": "Jul 1, 2026",
            "address": "Pawnee City, NE 68420",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None

    def test_allows_kansas_in_title(self):
        """Kansas is a target state — events mentioning it should NOT be rejected."""
        evt = {
            "title": "Kansas State Fair 2026",
            "date": "Sep 1, 2026",
            "address": "Hutchinson, KS",
            "link": "https://kansasstatefair.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "state fair Kansas", "KS")
        assert item is not None
        assert item.state == "KS"

    def test_allows_missouri_in_address(self):
        """Missouri is a target state — events in MO should NOT be rejected."""
        evt = {
            "title": "Home Show",
            "date": "Mar 1, 2026",
            "address": "St. Louis, MO 63101",
            "link": "https://example.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "home show Missouri", "MO")
        assert item is not None

    def test_guard_applies_to_serper_events_too(self):
        """The guard should reject serper_events, not just serper_organic."""
        evt = {
            "title": "Seward County Fair - Nebraska Association",
            "date": "Jul 1, 2026",
            "address": "",
            "link": "https://nebraskafairs.org/fairs.php?fairid=303",
            "_source_type": "serper_events",
        }
        assert normalize_event(evt, "county fair Kansas", "KS") is None


class TestDateFallback:
    """Test that dates are extracted from event names when the date field is empty."""

    def test_date_from_name_month_day_year(self):
        evt = {
            "title": "Calvert County Fair Returns Sept. 24, 2026",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "county fair Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-09-24"

    def test_date_from_name_month_year(self):
        evt = {
            "title": "ANNE ARUNDEL COUNTY FAIR - Updated June 2026",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "county fair Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-06-01"

    def test_date_from_name_year_only(self):
        evt = {
            "title": "Worcester County Fair 2026",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "county fair Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-01-01"

    def test_date_from_name_ordinal_suffix(self):
        evt = {
            "title": "Great Big Home Show - October 10th & 11th 2026",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "home show Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-10-10"

    def test_date_from_name_day_month_year(self):
        evt = {
            "title": "Suburban Maryland Home Show 2026 - 10th Jan, 2026",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "home show Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-01-10"

    def test_date_field_takes_priority_over_name(self):
        """If the date field has a value, it should be used, not the name."""
        evt = {
            "title": "Worcester County Fair 2026",
            "date": "Aug 15, 2026",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_events",
        }
        item = normalize_event(evt, "county fair Maryland", "MD")
        assert item is not None
        assert item.start_date == "2026-08-15"

    def test_no_date_at_all(self):
        """Events with no date in either field or name get empty start_date."""
        evt = {
            "title": "Frederick Home & Garden Expo",
            "date": "",
            "address": "",
            "link": "https://example.com",
            "_source_type": "serper_organic",
        }
        item = normalize_event(evt, "home show Maryland", "MD")
        assert item is not None
        assert item.start_date == ""
