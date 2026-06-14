"""Tests for the structured file ingest module."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from pipeline.models import EventItem
from pipeline.ingest import html_handler
from pipeline.ingest import csv_handler
from pipeline.ingest import json_handler
from pipeline.ingest import ingest_file


_FIXTURES = Path(__file__).parent / "fixtures"


# ── HTML Handler ──────────────────────────────────────────────────────────


def test_html_parse_extracts_events(festivalnet_html_path):
    events = html_handler.parse_html(festivalnet_html_path)
    assert len(events) >= 1
    for e in events:
        assert isinstance(e, EventItem)
        assert e.name
        assert e.source_type == "festivalnet"
        assert e.page_score == 3


def test_html_first_event_fields(festivalnet_html_path):
    events = html_handler.parse_html(festivalnet_html_path)
    assert len(events) >= 1
    e = events[0]
    assert e.name == "Handmade Market - June"
    assert e.state == "NJ"
    assert e.zip == "07302"
    assert e.city == "Jersey City"
    assert e.source_type == "festivalnet"


def test_html_extracts_web_url(festivalnet_html_path):
    events = html_handler.parse_html(festivalnet_html_path)
    e = events[0]
    assert e.primary_url == "https://jcdowntown.org/event/handmade-market/"


def test_html_filter_non_target_states(festivalnet_html_path):
    from pipeline.constants import STATE_ORDER

    events = html_handler.parse_html(festivalnet_html_path)
    states = {e.state for e in events}
    assert all(s in STATE_ORDER for s in states)


def test_html_parses_dates(festivalnet_html_path):
    events = html_handler.parse_html(festivalnet_html_path)
    assert len(events) >= 1
    e = events[0]
    assert e.start_date
    assert "2026" in e.start_date


def test_html_empty_file(tmp_path):
    path = tmp_path / "empty.html"
    path.write_text("<html><body></body></html>")
    events = html_handler.parse_html(path)
    assert events == []


def test_html_no_printed_pages(tmp_path):
    path = tmp_path / "no_pages.html"
    path.write_text(
        "<html><body>"
        "<table class='ProMembersSearchFullDetailsTable'>"
        "<tr><td colspan='3'>"
        "<h1 itemprop='name'>Test Event</h1>"
        "<div><font>Venue, "
        "<a href='/members/pro-search-results?state_local=MD'>MD</a> 21401"
        "</font></div>"
        "</td></tr>"
        "</table></body></html>"
    )
    events = html_handler.parse_html(path)
    assert len(events) == 1
    assert events[0].name == "Test Event"
    assert events[0].state == "MD"


def test_html_source_type(festivalnet_html_path):
    events = html_handler.parse_html(festivalnet_html_path)
    for e in events:
        assert e.source_type == "festivalnet"
        assert e.page_score == 3


# ── CSV Handler ───────────────────────────────────────────────────────────


def test_csv_parse_basic(tmp_path):
    path = tmp_path / "events.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "start_date", "city", "state"])
        writer.writerow(["Test Festival", "2026-06-15", "Annapolis", "MD"])

    events = csv_handler.parse_csv(path)
    assert len(events) == 1
    e = events[0]
    assert e.name == "Test Festival"
    assert e.start_date == "2026-06-15"
    assert e.city == "Annapolis"
    assert e.state == "MD"
    assert e.source_type == "csv_ingest"
    assert e.page_score == 3


def test_csv_parse_alternative_column_names(tmp_path):
    path = tmp_path / "alt.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Event Name", "Start Date", "Venue", "City", "State"])
        writer.writerow(["Spring Fair", "Apr 5, 2026", "Town Hall", "Richmond", "VA"])

    events = csv_handler.parse_csv(path)
    assert len(events) == 1
    e = events[0]
    assert e.name == "Spring Fair"
    assert e.city == "Richmond"
    assert e.state == "VA"


def test_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")
    events = csv_handler.parse_csv(path)
    assert events == []


def test_csv_missing_name_column(tmp_path):
    path = tmp_path / "bad.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["venue", "city", "state"])
        writer.writerow(["Town Hall", "Baltimore", "MD"])

    events = csv_handler.parse_csv(path)
    assert events == []


# ── JSON Handler ──────────────────────────────────────────────────────────


def test_json_parse_array(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Home Expo",
                    "startDate": "2026-05-01",
                    "city": "Dover",
                    "state": "DE",
                },
                {
                    "name": "Garden Show",
                    "start_date": "2026-06-15",
                    "city": "Newark",
                    "state": "NJ",
                },
            ]
        )
    )

    events = json_handler.parse_json(path)
    assert len(events) == 2
    assert events[0].name == "Home Expo"
    assert events[0].city == "Dover"
    assert events[0].state == "DE"
    assert events[1].name == "Garden Show"
    assert events[1].source_type == "json_ingest"
    assert events[1].page_score == 3


def test_json_parse_wrapped_object(tmp_path):
    path = tmp_path / "wrapped.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {"name": "Fall Fest", "date": "Oct 10, 2026", "state": "MD"},
                ]
            }
        )
    )

    events = json_handler.parse_json(path)
    assert len(events) == 1
    assert events[0].name == "Fall Fest"


def test_json_parse_nested_location(tmp_path):
    path = tmp_path / "nested.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "name": "County Fair",
                        "date": "July 4, 2026",
                        "location": {
                            "name": "Fairgrounds",
                            "city": "Frederick",
                            "state": "MD",
                            "zip": "21701",
                        },
                        "website": "https://example.com/fair",
                    }
                ],
            }
        )
    )

    events = json_handler.parse_json(path)
    assert len(events) == 1
    e = events[0]
    assert e.name == "County Fair"
    assert e.city == "Frederick"
    assert e.state == "MD"
    assert e.zip == "21701"
    assert e.primary_url == "https://example.com/fair"


def test_json_empty_file(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]")
    events = json_handler.parse_json(path)
    assert events == []


# ── Dispatcher / ingest_file ──────────────────────────────────────────────


def test_ingest_file_html(festivalnet_html_path):
    events = ingest_file(str(festivalnet_html_path))
    assert len(events) >= 1
    for e in events:
        assert e.source_type == "festivalnet"


def test_ingest_file_csv(tmp_path):
    path = tmp_path / "test.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "city", "start_date"])
        writer.writerow(["CSV Event", "DC", "2026-08-01"])

    events = ingest_file(str(path))
    assert len(events) == 1
    assert events[0].name == "CSV Event"


def test_ingest_file_json(tmp_path):
    path = tmp_path / "test.json"
    path.write_text(json.dumps([{"name": "JSON Event", "startDate": "2026-09-01"}]))

    events = ingest_file(str(path))
    assert len(events) == 1
    assert events[0].name == "JSON Event"


def test_ingest_file_unsupported_extension(tmp_path):
    path = tmp_path / "test.xml"
    path.write_text("<xml></xml>")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        ingest_file(str(path))


def test_ingest_file_not_found():
    with pytest.raises(FileNotFoundError):
        ingest_file("/nonexistent/path.html")
