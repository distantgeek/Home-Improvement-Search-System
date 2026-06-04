"""
JSON file ingest handler.

Reads a JSON file containing an array of event objects and converts them
to EventItem instances. Supports both flat objects and nested structures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline.normalize import parse_dates

if TYPE_CHECKING:
    from pipeline.models import EventItem

logger = logging.getLogger(__name__)

_SOURCE_TYPE = "json_ingest"
_DEFAULT_PAGE_SCORE = 3


def _extract(data: dict, key: str, *fallbacks: str) -> str:
    for k in (key, *fallbacks):
        val = data.get(k, "")
        if val:
            return str(val).strip()
    return ""


def parse_json(path: Path) -> list[EventItem]:
    from pipeline.models import EventItem

    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        records = raw.get("events", raw.get("data", raw.get("results", [])))
        if isinstance(records, dict):
            records = [records]
    elif isinstance(raw, list):
        records = raw
    else:
        logger.error("JSON root must be a list or object: %s", path)
        return []

    if not isinstance(records, list):
        records = [records]

    events = []
    for rec in records:
        if not isinstance(rec, dict):
            continue

        name = _extract(rec, "name", "title", "event_name", "eventName")
        if not name:
            continue

        raw_date = _extract(
            rec, "date", "start_date", "startDate", "event_date", "eventDate"
        )
        start_date, end_date = parse_dates(raw_date)

        raw_end = _extract(rec, "end_date", "endDate", "date_end", "dateEnd")
        if raw_end and not end_date:
            _, end_date = parse_dates(raw_end)

        location = rec.get("location", rec.get("venue", {}))
        if isinstance(location, dict):
            venue = _extract(location, "name", "venue")
            city = _extract(location, "city")
            state_rec = _extract(location, "state", "region")
            zip_code = _extract(location, "zip", "postal_code", "postalCode")
        else:
            venue = str(location) if location else ""
            city = ""
            state_rec = ""
            zip_code = ""

        address_parts = [
            _extract(rec, "venue", "venue_name"),
            _extract(rec, "city", "town"),
            _extract(rec, "state", "region"),
        ]
        addr_full = ", ".join(p for p in address_parts if p)
        if not addr_full and isinstance(location, dict):
            addr = location.get("address", {})
            if isinstance(addr, dict):
                parts = [
                    addr.get("streetAddress", ""),
                    addr.get("addressLocality", ""),
                    addr.get("addressRegion", ""),
                ]
                addr_full = ", ".join(p for p in parts if p)
            elif isinstance(addr, str):
                addr_full = addr

        events.append(
            EventItem(
                name=name,
                start_date=start_date,
                end_date=end_date or start_date,
                venue=_extract(rec, "venue", "venue_name") or venue,
                city=_extract(rec, "city", "town") or city,
                state=_extract(rec, "state", "region") or state_rec,
                county=_extract(rec, "county", "county_name", "countyName"),
                zip=_extract(rec, "zip", "zip_code", "zipCode", "postal_code")
                or zip_code,
                event_type=_extract(
                    rec,
                    "event_type",
                    "eventType",
                    "type",
                    "category",
                    "event_category",
                ),
                primary_url=_extract(
                    rec,
                    "primary_url",
                    "primaryUrl",
                    "website",
                    "web",
                    "url",
                    "link",
                ),
                source_type=_SOURCE_TYPE,
                source_queries=["json_ingest"],
                attendance=_extract(
                    rec, "attendance", "attendanceCount", "expected_attendance"
                ),
                contact=_extract(
                    rec, "contact", "email", "contact_info", "contactInfo"
                ),
                page_score=_DEFAULT_PAGE_SCORE,
                addr_full=addr_full,
            )
        )

    logger.info("JSON: parsed %d events from %s", len(events), path.name)
    return events
