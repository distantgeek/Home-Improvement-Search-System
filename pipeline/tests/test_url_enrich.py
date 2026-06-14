"""Tests for pipeline.fetchers.url_enrich."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses as responses_lib

from pipeline.fetchers.url_enrich import (
    _CITY_STATE_ZIP_RE,
    _extract_heuristic,
    _is_blocked_url,
    _parse_json_ld_address,
    _parse_microdata_address,
    _render_via_sidecar,
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


# ── Retry logic ────────────────────────────────────────────────────────────────


class TestFetchAndExtractRetry:
    def test_retry_on_timeout_then_success(self):
        """First request times out, retry succeeds with longer timeout."""
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        from pipeline.fetchers.url_enrich import _fetch_and_extract

        target_url = "https://www.example.com/events/home-show"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.url = target_url

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.ConnectionError("timeout")
            return mock_resp

        with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
            mock_session.get.side_effect = side_effect
            result = _fetch_and_extract(target_url)
        assert result is not None
        assert result["zip"] == "21702"
        assert call_count == 2

    def test_retry_exhausted_returns_none(self):
        """Both attempts fail — returns None."""
        from pipeline.fetchers.url_enrich import _fetch_and_extract

        with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
            mock_session.get.side_effect = requests.ConnectionError("timeout")
            result = _fetch_and_extract("https://www.example.com/events/home-show")
        assert result is None
        assert mock_session.get.call_count == 2

    @responses_lib.activate
    def test_no_retry_on_http_error(self):
        """HTTP 404 returns None immediately — no retry."""
        url = "https://www.example.com/events/home-show"
        responses_lib.add(responses_lib.GET, url, status=404)
        from pipeline.fetchers.url_enrich import _fetch_and_extract

        result = _fetch_and_extract(url)
        assert result is None
        assert len(responses_lib.calls) == 1

    @responses_lib.activate
    def test_no_retry_on_no_address(self):
        """Page loads but has no address — returns empty dict, no retry."""
        url = "https://www.example.com/events/home-show"
        responses_lib.add(
            responses_lib.GET,
            url,
            body="<html><body>No address here</body></html>",
            status=200,
            content_type="text/html",
        )
        from pipeline.fetchers.url_enrich import _fetch_and_extract

        result = _fetch_and_extract(url)
        assert result == {}


class TestEnrichOneEventRetry:
    def test_event_level_retry_on_fetch_error(self):
        """All URLs fail with fetch errors, then primary URL retry succeeds."""
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.url = "https://www.example.com/events/home-show"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise requests.ConnectionError("timeout")
            return mock_resp

        with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
            mock_session.get.side_effect = side_effect
            event = _make_event(zip_code="", city="", county="")
            count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"

    @responses_lib.activate
    def test_no_event_retry_when_page_has_no_address(self):
        """If a page loaded but had no address, no event-level retry."""
        url = "https://www.example.com/events/home-show"
        responses_lib.add(
            responses_lib.GET,
            url,
            body="<html><body>No address data</body></html>",
            status=200,
            content_type="text/html",
        )
        event = _make_event(zip_code="", city="", county="")
        count = enrich_from_urls([event])
        assert count == 0

    def test_no_event_retry_when_all_urls_blocked(self):
        """Blocked URLs return 'blocked' immediately, no retry."""
        event = _make_event(primary_url="http://localhost/evil", zip_code="", county="")
        count = enrich_from_urls([event])
        assert count == 0

    def test_event_retry_also_fails(self):
        """Both initial fetch and event-level retry fail — returns fetch_failed."""
        with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
            mock_session.get.side_effect = requests.ConnectionError("timeout")
            event = _make_event(zip_code="", city="", county="")
            count = enrich_from_urls([event])
        assert count == 0


# ── Sidecar integration ────────────────────────────────────────────────────────


class TestRenderViaSidecar:
    def test_returns_none_when_sidecar_url_not_set(self):
        """No sidecar URL configured — returns None immediately."""
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", ""):
            result = _render_via_sidecar("https://www.example.com/events/home-show")
        assert result is None

    def test_returns_none_for_blocked_url(self):
        """Blocked URLs are not sent to sidecar."""
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            result = _render_via_sidecar("http://localhost/evil")
        assert result is None

    def test_returns_none_on_connection_error(self):
        """Sidecar unreachable — returns None."""
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
                mock_session.post.side_effect = requests.ConnectionError("refused")
                result = _render_via_sidecar("https://www.example.com/events/home-show")
        assert result is None

    def test_returns_none_on_sidecar_error(self):
        """Sidecar returns 502 — returns None."""
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
                mock_resp = MagicMock()
                mock_resp.status_code = 502
                mock_resp.json.return_value = {"error": "Failed to load page"}
                mock_session.post.return_value = mock_resp
                result = _render_via_sidecar("https://www.example.com/events/home-show")
        assert result is None

    def test_extracts_address_from_sidecar_html(self):
        """Sidecar returns rendered HTML with JSON-LD address."""
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "html": html,
                    "status": 200,
                    "url": "https://www.example.com/events/home-show",
                }
                mock_session.post.return_value = mock_resp
                result = _render_via_sidecar("https://www.example.com/events/home-show")
        assert result is not None
        assert result["zip"] == "21702"
        assert result["city"] == "Frederick"

    def test_returns_empty_dict_for_no_address(self):
        """Sidecar returns HTML but no address data — returns empty dict."""
        html = "<html><body>Just a page with no address</body></html>"
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "html": html,
                    "status": 200,
                    "url": "https://www.example.com/events/home-show",
                }
                mock_session.post.return_value = mock_resp
                result = _render_via_sidecar("https://www.example.com/events/home-show")
        assert result == {}


class TestEnrichOneSidecar:
    def test_sidecar_enriched_on_static_fetch_failure(self):
        """Static fetch fails, sidecar succeeds — returns sidecar_enriched."""
        html = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "html": html,
            "status": 200,
            "url": "https://www.example.com/events/home-show",
        }

        call_count = 0

        def get_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise requests.ConnectionError("timeout")

        with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
            mock_session.get.side_effect = get_side_effect
            mock_session.post.return_value = mock_resp
            with patch(
                "pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"
            ):
                event = _make_event(zip_code="", city="", county="")
                count = enrich_from_urls([event])
        assert count == 1
        assert event.zip == "21702"

    @responses_lib.activate
    def test_sidecar_called_when_page_has_no_address(self):
        """JS-heavy page: static fetch loads but finds no address → sidecar is tried."""
        url = "https://www.example.com/events/home-show"
        html_with_address = _html_with_json_ld(
            {
                "@type": "PostalAddress",
                "addressLocality": "Frederick",
                "addressRegion": "MD",
                "postalCode": "21702",
            }
        )
        responses_lib.add(
            responses_lib.GET,
            url,
            body="<html><body>No address data in static HTML</body></html>",
            status=200,
            content_type="text/html",
        )
        mock_sidecar_resp = MagicMock()
        mock_sidecar_resp.status_code = 200
        mock_sidecar_resp.json.return_value = {
            "html": html_with_address,
            "url": url,
        }
        event = _make_event(zip_code="", city="", county="")
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            with patch("pipeline.fetchers.url_enrich._SESSION") as mock_session:
                mock_session.get.side_effect = lambda *a, **kw: responses_lib.calls and MagicMock(
                    status_code=200,
                    text="<html><body>No address data in static HTML</body></html>",
                    headers={"Content-Type": "text/html"},
                    url=url,
                )
                mock_session.post.return_value = mock_sidecar_resp
                # Use enrich_from_urls but mock at SESSION level
        # Simpler: patch _fetch_and_extract and _render_via_sidecar directly
        with patch("pipeline.fetchers.url_enrich._fetch_and_extract", return_value={}):
            with patch(
                "pipeline.fetchers.url_enrich._render_via_sidecar",
                return_value={"zip": "21702", "city": "Frederick", "state": "MD"},
            ) as mock_sidecar:
                with patch(
                    "pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"
                ):
                    count = enrich_from_urls([event])
        assert mock_sidecar.called, "Sidecar should be called for JS-heavy pages"
        assert count == 1
        assert event.zip == "21702"

    def test_sidecar_not_called_when_url_empty(self):
        """No primary_url — no sidecar call."""
        event = _make_event(primary_url="", zip_code="", county="")
        with patch("pipeline.fetchers.url_enrich._SIDECAR_URL", "http://sidecar:8000"):
            count = enrich_from_urls([event])
        assert count == 0


# ── Multi-event listing page deduplication ───────────────────────────────────


class TestMultiEventJsonLd:
    def test_best_matching_event_selected_on_listing_page(self):
        """When a page has multiple Event JSON-LD blocks, the one matching the
        event name is returned rather than the first."""
        from pipeline.fetchers.url_enrich import _extract_json_ld
        from bs4 import BeautifulSoup

        html = """<html><head>
        <script type="application/ld+json">[
          {
            "@type": "Event",
            "name": "Annapolis Boat Show",
            "location": {"address": {"@type": "PostalAddress",
              "addressLocality": "Annapolis", "addressRegion": "MD",
              "postalCode": "21401"}}
          },
          {
            "@type": "Event",
            "name": "Maryland Home Show",
            "location": {"address": {"@type": "PostalAddress",
              "addressLocality": "Timonium", "addressRegion": "MD",
              "postalCode": "21093"}}
          },
          {
            "@type": "Event",
            "name": "Frederick County Fair",
            "location": {"address": {"@type": "PostalAddress",
              "addressLocality": "Frederick", "addressRegion": "MD",
              "postalCode": "21702"}}
          }
        ]</script>
        </head><body></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_json_ld(soup, event_name="Frederick County Fair")
        assert result is not None
        assert result["name"] == "Frederick County Fair"

    def test_graph_wrapper_events_are_collected(self):
        """@graph-wrapped JSON-LD events are flattened and considered."""
        from pipeline.fetchers.url_enrich import _extract_json_ld
        from bs4 import BeautifulSoup

        html = """<html><head>
        <script type="application/ld+json">{
          "@context": "https://schema.org",
          "@graph": [
            {
              "@type": "Event",
              "name": "Spring Home Show",
              "location": {"address": {"postalCode": "21201", "addressLocality": "Baltimore"}}
            }
          ]
        }</script>
        </head><body></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_json_ld(soup, event_name="Spring Home Show")
        assert result is not None
        assert result.get("name") == "Spring Home Show"


# ── Context-aware heuristic ──────────────────────────────────────────────────


class TestHeuristicContextWindow:
    def test_extracts_zip_near_event_name_not_first_zip(self):
        """When the page has multiple ZIPs, the one near the event name wins."""
        text = (
            "Annual Craft Fair Portland OR 97201 "
            "followed by lots of other content ... "
            "Maryland Home Show Frederick MD 21702 great event"
        )
        result = _extract_heuristic(text, event_name="Maryland Home Show")
        assert result.get("zip") == "21702", (
            "Should return ZIP near the event name, not the first ZIP on the page"
        )

    def test_falls_back_to_full_page_when_name_not_found(self):
        """If event name is absent from page text, falls back to full-page scan."""
        text = "Some venue Baltimore, MD 21201 hosts events"
        result = _extract_heuristic(text, event_name="Event Not On This Page")
        assert result.get("zip") == "21201"
