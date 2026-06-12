"""Tests for pipeline.fetchers.url_enrich."""

import json
from unittest.mock import patch

import pytest
import responses as responses_lib

from pipeline.fetchers.url_enrich import (
    _CITY_STATE_ZIP_RE,
    _extract_heuristic,
    _is_blocked_url,
    _parse_json_ld_address,
    _parse_microdata_address,
    enrich_from_urls,
)
from pipeline.models import EventItem


def _make_event(
    name: str = "Frederick County Home Show",
    primary_url: str = "https://www.example.com/events/home-show",
    zip_code: str = "",
    city: str = "",
    state: str = "",
    county: str = "",
    venue: str = "",
    sources: list | None = None,
) -> EventItem:
    return EventItem(
        name=name,
        primary_url=primary_url,
        zip=zip_code,
        city=city,
        state=state,
        county=county,
        venue=venue,
        sources=sources or [],
    )


def _html_with_json_ld(address_dict: dict, event_name: str = "Home Show") -> str:
    addr = json.dumps(address_dict)
    return f"""<html><head>
<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "{event_name}",
  "location": {{
    "@type": "Place",
    "name": "Fairgrounds",
    "address": {addr}
  }}
}}</script>
</head><body><h1>{event_name}</h1></body></html>"""


def _html_with_microdata(
    street: str = "797 E Patrick St",
    city: str = "Frederick",
    state: str = "MD",
    zip_code: str = "21702",
) -> str:
    return f"""<html><body>
<div itemscope itemtype="https://schema.org/Event">
  <span itemprop="name">Home Show</span>
  <div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
    <span itemprop="streetAddress">{street}</span>
    <span itemprop="addressLocality">{city}</span>
    <span itemprop="addressRegion">{state}</span>
    <span itemprop="postalCode">{zip_code}</span>
  </div>
</div>
</body></html>"""


def _html_with_heuristic_address() -> str:
    return """<html><body>
<h1>Home Show</h1>
<p>Join us at the Frederick Fairgrounds, 797 E Patrick St, Frederick, MD 21702</p>
</body></html>"""


# ── SSRF protection ──────────────────────────────────────────────────────────


class TestIsBlockedUrl:
    def test_blocks_http(self):
        assert _is_blocked_url("http://example.com") is True

    def test_allows_https(self):
        assert _is_blocked_url("https://example.com") is False

    def test_blocks_localhost(self):
        assert _is_blocked_url("https://localhost/path") is True

    def test_blocks_internal_suffix(self):
        assert _is_blocked_url("https://app.local/path") is True

    def test_blocks_test_suffix(self):
        assert _is_blocked_url("https://app.test/path") is True

    def test_blocks_empty_string(self):
        assert _is_blocked_url("") is True

    @patch("pipeline.fetchers.url_enrich._is_private_ip", return_value=True)
    def test_blocks_private_ip(self, mock_ip):
        assert _is_blocked_url("https://10.0.0.1/path") is True

    def test_allows_normal_domain(self):
        assert _is_blocked_url("https://www.homeshowexpo.com/events/123") is False


# ── JSON-LD address parsing ──────────────────────────────────────────────────


class TestParseJsonLdAddress:
    def test_full_address(self):
        data = {
            "@type": "Event",
            "location": {
                "@type": "Place",
                "name": "Fairgrounds",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "797 E Patrick St",
                    "addressLocality": "Frederick",
                    "addressRegion": "MD",
                    "postalCode": "21702",
                },
            },
        }
        result = _parse_json_ld_address(data)
        assert result["city"] == "Frederick"
        assert result["state"] == "MD"
        assert result["zip"] == "21702"
        assert result["venue"] == "Fairgrounds"
        assert result["streetAddress"] == "797 E Patrick St"

    def test_missing_location(self):
        assert _parse_json_ld_address({"@type": "Event"}) == {}

    def test_partial_address(self):
        data = {
            "location": {
                "address": {
                    "addressLocality": "Frederick",
                    "addressRegion": "MD",
                },
            },
        }
        result = _parse_json_ld_address(data)
        assert result["city"] == "Frederick"
        assert result["state"] == "MD"
        assert "zip" not in result


# ── Microdata address parsing ────────────────────────────────────────────────


class TestParseMicrodataAddress:
    def test_full_address(self):
        data = {
            "streetAddress": "797 E Patrick St",
            "addressLocality": "Frederick",
            "addressRegion": "MD",
            "postalCode": "21702",
            "name": "Fairgrounds",
        }
        result = _parse_microdata_address(data)
        assert result["city"] == "Frederick"
        assert result["state"] == "MD"
        assert result["zip"] == "21702"
        assert result["venue"] == "Fairgrounds"

    def test_empty_dict(self):
        assert _parse_microdata_address({}) == {}


# ── Heuristic extraction ──────────────────────────────────────────────────────


class TestExtractHeuristic:
    def test_city_state_zip(self):
        text = "797 E Patrick St, Frederick, MD 21702"
        result = _extract_heuristic(text)
        assert result["city"] == "Frederick"
        assert result["state"] == "MD"
        assert result["zip"] == "21702"

    def test_city_state_zip_no_street(self):
        text = "Frederick, MD 21702"
        result = _extract_heuristic(text)
        assert result["city"] == "Frederick"
        assert result["state"] == "MD"
        assert result["zip"] == "21702"

    def test_zip_only(self):
        text = "Event venue somewhere 21702"
        result = _extract_heuristic(text)
        assert result["zip"] == "21702"

    def test_street_address(self):
        text = "797 E Patrick St, Frederick, MD 21702"
        result = _extract_heuristic(text)
        assert result.get("streetAddress") is not None
        assert "Patrick" in result["streetAddress"]

    def test_no_address_data(self):
        result = _extract_heuristic("Just some random text without addresses")
        assert "zip" not in result
        assert "city" not in result


# ── City/State/ZIP regex ─────────────────────────────────────────────────────


class TestCityStateZipRegex:
    def test_standard_format(self):
        m = _CITY_STATE_ZIP_RE.search("797 E Patrick St, Frederick, MD 21702")
        assert m is not None
        assert m.group(1).strip() == "Frederick"
        assert m.group(2) == "MD"
        assert m.group(3) == "21702"

    def test_city_state_zip_only(self):
        m = _CITY_STATE_ZIP_RE.search("Frederick, MD 21702")
        assert m is not None
        assert m.group(1).strip() == "Frederick"
        assert m.group(2) == "MD"

    def test_multi_word_city(self):
        m = _CITY_STATE_ZIP_RE.search("New Brunswick, NJ 08901")
        assert m is not None
        assert m.group(1).strip() == "New Brunswick"


# ── Full enrichment via HTTP ──────────────────────────────────────────────────


class TestEnrichFromUrls:
    @responses_lib.activate
    def test_json_ld_enrichment(self):
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "streetAddress": "797 E Patrick St",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="", city="", state="", county="")
        count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"
        assert event.city == "Frederick"
        assert event.state == "MD"
        assert any(s.get("sourceType") == "url_enrich" for s in event.sources)

    @responses_lib.activate
    def test_microdata_enrichment(self):
        html = _html_with_microdata()
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="", city="", county="")
        count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"
        assert event.city == "Frederick"

    @responses_lib.activate
    def test_heuristic_enrichment(self):
        html = _html_with_heuristic_address()
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="", city="", county="")
        count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"

    def test_skips_events_with_all_fields(self):
        event = _make_event(zip_code="21702", city="Frederick", county="Frederick")
        count = enrich_from_urls([event])
        assert count == 0

    def test_returns_zero_for_empty_list(self):
        assert enrich_from_urls([]) == 0

    @responses_lib.activate
    def test_does_not_overwrite_existing_fields(self):
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "streetAddress": "100 Main St",
                "addressLocality": "Baltimore",
                "addressRegion": "MD",
                "postalCode": "21201",
            }
        )
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="21702", city="Frederick", state="MD", county="")
        count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"
        assert event.city == "Frederick"
        assert event.state == "MD"

    @responses_lib.activate
    def test_404_page_skipped(self):
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            status=404,
        )
        event = _make_event(zip_code="", county="")
        count = enrich_from_urls([event])
        assert count == 0

    @responses_lib.activate
    def test_non_html_content_skipped(self):
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body="just some text",
            status=200,
            content_type="application/pdf",
        )
        event = _make_event(zip_code="", county="")
        count = enrich_from_urls([event])
        assert count == 0

    def test_blocked_url_skipped(self):
        event = _make_event(primary_url="http://localhost/evil")
        count = enrich_from_urls([event])
        assert count == 0

    @responses_lib.activate
    def test_alternate_url_used(self):
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        responses_lib.add(
            responses_lib.GET,
            "https://www.alt-site.com/show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(
            primary_url="",
            sources=[
                {"url": "https://www.alt-site.com/show", "sourceType": "serper_events"}
            ],
        )
        count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"

    @responses_lib.activate
    def test_source_entry_added_on_enrichment(self):
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        responses_lib.add(
            responses_lib.GET,
            "https://www.example.com/events/home-show",
            body=html,
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="", county="")
        enrich_from_urls([event])
        url_enrich_sources = [
            s for s in event.sources if s.get("sourceType") == "url_enrich"
        ]
        assert len(url_enrich_sources) == 1
        assert (
            url_enrich_sources[0]["url"] == "https://www.example.com/events/home-show"
        )
