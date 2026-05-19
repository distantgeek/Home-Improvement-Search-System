"""Tests for pipeline.fetchers.serper."""
import pytest
import responses as responses_lib

from pipeline.fetchers.serper import (
    SERPER_URL,
    _call_serper,
    build_all_queries,
    build_queries_for_state,
    fetch_all,
)
from pipeline.constants import COUNTIES


class TestBuildQueriesForState:
    def test_generates_home_show_queries(self):
        queries = build_queries_for_state(COUNTIES["MD"], "MD", ["Home Show"])
        assert any("home show" in q.lower() and "maryland" in q.lower() for q in queries)

    def test_county_fair_generates_per_county_query(self):
        queries = build_queries_for_state(["Frederick", "Carroll"], "MD", ["County Fair"])
        assert any("Frederick County" in q for q in queries)
        assert any("Carroll County" in q for q in queries)

    def test_no_duplicates(self):
        queries = build_queries_for_state(COUNTIES["MD"], "MD", ["Home Show", "Home & Garden"])
        assert len(queries) == len(set(queries))

    def test_state_fair_single_query(self):
        queries = build_queries_for_state(COUNTIES["MD"], "MD", ["State Fair"])
        state_fair_queries = [q for q in queries if "state fair" in q.lower()]
        assert len(state_fair_queries) == 1


class TestBuildAllQueries:
    def test_covers_all_states(self):
        queries = build_all_queries(["Home Show"])
        query_text = " ".join(queries).lower()
        for state_name in ("maryland", "virginia", "pennsylvania", "new jersey", "delaware"):
            assert state_name in query_text

    def test_no_duplicates_across_states(self):
        queries = build_all_queries(["State Fair"])
        assert len(queries) == len(set(queries))

    def test_uses_all_event_types_by_default(self):
        queries = build_all_queries()
        query_text = " ".join(queries).lower()
        assert "home show" in query_text
        assert "county fair" in query_text


@responses_lib.activate
class TestCallSerper:
    def test_returns_events_results_when_present(self, serper_events_payload):
        responses_lib.add(
            responses_lib.POST,
            SERPER_URL,
            json=serper_events_payload,
            status=200,
        )
        import requests
        with requests.Session() as session:
            result = _call_serper("test-key", "home show Maryland", session)
        assert len(result) == 3
        assert all(r.get("_source_type") == "serper_events" for r in result)

    def test_falls_back_to_organic_when_no_events(self, serper_organic_payload):
        responses_lib.add(
            responses_lib.POST,
            SERPER_URL,
            json=serper_organic_payload,
            status=200,
        )
        import requests
        with requests.Session() as session:
            result = _call_serper("test-key", "home show Maryland", session)
        # Should return parsed organic results (Wikipedia filtered out)
        assert all(r.get("_source_type") == "serper_organic" for r in result)

    def test_raises_on_401(self):
        responses_lib.add(responses_lib.POST, SERPER_URL, status=401)
        import requests
        with requests.Session() as session:
            with pytest.raises(requests.HTTPError):
                _call_serper("bad-key", "query", session)


@responses_lib.activate
class TestFetchAll:
    def test_dry_run_returns_empty(self):
        result = fetch_all("key", ["query1", "query2"], dry_run=True)
        assert result == []
        assert len(responses_lib.calls) == 0

    def test_normalizes_raw_events_to_event_items(self, serper_events_payload):
        responses_lib.add(
            responses_lib.POST,
            SERPER_URL,
            json=serper_events_payload,
            status=200,
        )
        result = fetch_all("test-key", ["home show Maryland"])
        assert len(result) > 0
        from pipeline.models import EventItem
        assert all(isinstance(r, EventItem) for r in result)

    def test_skips_events_with_empty_title(self, serper_events_payload):
        payload = {"eventsResults": [{"title": "", "link": "https://x.com"}]}
        responses_lib.add(responses_lib.POST, SERPER_URL, json=payload, status=200)
        result = fetch_all("test-key", ["query"])
        assert result == []
