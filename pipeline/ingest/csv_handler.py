"""
CSV file ingest handler.

Reads a CSV file with event data columns and converts rows to EventItem objects.
Expected columns (case-insensitive): name, start_date, end_date, venue, city,
state, county, zip, event_type, primary_url, attendance, contact, description.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.normalize import parse_dates

if TYPE_CHECKING:
    from pipeline.models import EventItem

logger = logging.getLogger(__name__)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_FIELD_MAP: dict[str, list[str]] = {
    "name": ["name", "event name", "title", "show name"],
    "start_date": ["start_date", "start date", "begins", "start"],
    "end_date": ["end_date", "end date", "ends", "end"],
    "venue": ["venue", "location", "venue name"],
    "city": ["city", "town"],
    "state": ["state"],
    "county": ["county"],
    "zip": ["zip", "zip code", "zipcode", "postal code"],
    "event_type": ["event_type", "event type", "type", "category"],
    "primary_url": [
        "primary_url",
        "primary url",
        "website",
        "web",
        "url",
        "link",
    ],
    "attendance": ["attendance", "attendance #", "expected attendance"],
    "contact": ["contact", "email", "phone", "contact info"],
    "description": ["description", "desc", "details", "notes"],
}

_SOURCE_TYPE = "csv_ingest"
_DEFAULT_PAGE_SCORE = 3


def _build_index(headers: list[str]) -> dict[str, int]:
    lower = [h.strip().lower() for h in headers]
    index = {}
    for field, aliases in _FIELD_MAP.items():
        for alias in aliases:
            for i, h in enumerate(lower):
                if h == alias.lower():
                    index[field] = i
                    break
            if field in index:
                break
    return index


def _get(row: list[str], index: dict[str, int], field: str) -> str:
    col = index.get(field)
    if col is None:
        return ""
    return row[col].strip()


def parse_csv(path: Path) -> list[EventItem]:
    from pipeline.models import EventItem

    events = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        if not headers:
            logger.warning("CSV file is empty: %s", path)
            return []

        idx = _build_index(headers)
        if "name" not in idx:
            logger.error(
                "CSV missing required 'name' column — found columns: %s",
                ", ".join(h.strip().lower() for h in headers),
            )
            return []

        for row in reader:
            name = _get(row, idx, "name")
            if not name:
                continue

            raw_date = _get(row, idx, "start_date")
            if _ISO_DATE_RE.match(raw_date):
                start_date = raw_date
                raw_end = _get(row, idx, "end_date")
                end_date = raw_end if _ISO_DATE_RE.match(raw_end) else start_date
            else:
                start_date, end_date = parse_dates(raw_date)
                raw_end = _get(row, idx, "end_date")
                if raw_end and not end_date:
                    _, end_date = parse_dates(raw_end)

            address_parts = [
                _get(row, idx, "venue"),
                _get(row, idx, "city"),
                _get(row, idx, "state"),
            ]
            addr_full = ", ".join(p for p in address_parts if p)

            events.append(
                EventItem(
                    name=name,
                    start_date=start_date,
                    end_date=end_date or start_date,
                    venue=_get(row, idx, "venue"),
                    city=_get(row, idx, "city"),
                    state=_get(row, idx, "state"),
                    county=_get(row, idx, "county"),
                    zip=_get(row, idx, "zip"),
                    event_type=_get(row, idx, "event_type"),
                    primary_url=_get(row, idx, "primary_url"),
                    source_type=_SOURCE_TYPE,
                    source_queries=["csv_ingest"],
                    attendance=_get(row, idx, "attendance"),
                    contact=_get(row, idx, "contact"),
                    page_score=_DEFAULT_PAGE_SCORE,
                    addr_full=addr_full,
                )
            )

    logger.info("CSV: parsed %d events from %s", len(events), path.name)
    return events
