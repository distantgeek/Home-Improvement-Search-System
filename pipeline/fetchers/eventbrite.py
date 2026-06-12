"""Eventbrite Discovery API client — Tier 1 structured event source.

NOTE: Eventbrite's Discovery API (events/search) was restricted around 2023
and may require enterprise access. If the API returns HTTP 401/403, this
fetcher logs a warning and returns an empty list — the pipeline continues
with Serper.dev (Tier 2) as the sole source.
"""

from __future__ import annotations

import logging
from datetime import date

import requests

from ..constants import EVENT_TYPES, STATE_NAMES, STATE_ORDER
from ..models import EventItem
from ..normalize import infer_event_type, parse_dates

logger = logging.getLogger(__name__)

EVENTBRITE_SEARCH_URL = "https://www.eventbriteapi.com/v3/events/search/"

# Approximate geographic centroids for lat/lng radius queries
_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "MD": (39.0458, -76.6413),
    "VA": (37.4316, -78.6569),
    "PA": (41.2033, -77.1945),
    "DC": (38.9072, -77.0369),
    "NJ": (40.0583, -74.4057),
    "DE": (38.9108, -75.5277),
    "MO": (38.5739, -92.6038),
    "IL": (40.0795, -89.4347),
    "OH": (40.2862, -82.7937),
    "KS": (38.4985, -98.3184),
}
_SEARCH_RADIUS = "100mi"

_KEYWORD_MAP: dict[str, str] = {
    "Home Show": "home show home improvement expo",
    "Home & Garden": "home garden show outdoor living",
    "County Fair": "county fair",
    "State Fair": "state fair",
    "Art & Craft": "art fair craft show",
    "Food Festival": "food festival wine festival",
    "Fall Festival": "fall festival harvest festival",
    "Community Festival": "community festival cultural festival",
}


def _normalize_eb_event(raw: dict, query_label: str) -> EventItem | None:
    """Convert a raw Eventbrite API event dict to an EventItem."""
    name = (raw.get("name") or {}).get("text", "").strip()
    if not name:
        return None

    venue_obj = raw.get("venue") or {}
    address = venue_obj.get("address") or {}

    city = address.get("city", "")
    state_code = address.get("region", "")
    zip_code = (address.get("postal_code", "") or "")[:5]  # trim +4 extension

    venue_name = venue_obj.get("name", "")
    addr_parts = [venue_name, address.get("address_1", ""), city, state_code, zip_code]
    addr_full = ", ".join(p for p in addr_parts if p)

    start_obj = raw.get("start") or {}
    end_obj = raw.get("end") or {}
    start_date, _ = parse_dates(start_obj.get("local", ""))
    end_date, _ = parse_dates(end_obj.get("local", ""))
    if not end_date:
        end_date = start_date

    url = raw.get("url", "")

    return EventItem(
        name=name,
        start_date=start_date,
        end_date=end_date,
        venue=venue_name,
        city=city,
        state=state_code if state_code in STATE_ORDER else "",
        county="",
        county_full="",
        zip=zip_code,
        event_type=infer_event_type(query_label, name),
        primary_url=url,
        source_type="eventbrite",
        source_queries=[query_label],
        page_score=2,  # Eventbrite URLs are canonical
        addr_full=addr_full,
    )


def fetch_all(
    api_key: str,
    event_types: list[str] | None = None,
    *,
    dry_run: bool = False,
) -> list[EventItem]:
    """Fetch from Eventbrite Discovery API for all target states.

    Returns an empty list (without raising) if the API is inaccessible.
    """
    if dry_run:
        logger.info(
            "[dry-run] Would call Eventbrite API for %d states", len(STATE_ORDER)
        )
        return []

    types = event_types or EVENT_TYPES
    keywords = " ".join(_KEYWORD_MAP[t] for t in types if t in _KEYWORD_MAP)
    start_range = f"{date.today().isoformat()}T00:00:00Z"

    events: list[EventItem] = []
    headers = {"Authorization": f"Bearer {api_key}"}

    with requests.Session() as session:
        for state in STATE_ORDER:
            if state not in _STATE_CENTROIDS:
                continue
            lat, lng = _STATE_CENTROIDS[state]
            page = 1

            while True:
                try:
                    resp = session.get(
                        EVENTBRITE_SEARCH_URL,
                        headers=headers,
                        params={
                            "q": keywords,
                            "location.latitude": lat,
                            "location.longitude": lng,
                            "location.within": _SEARCH_RADIUS,
                            "start_date.range_start": start_range,
                            "expand": "venue,category,format",
                            "page": page,
                            "page_size": 50,
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else 0
                    if status in (401, 403):
                        logger.warning(
                            "Eventbrite API access denied (HTTP %d) — "
                            "Discovery API may require enterprise access. "
                            "Continuing with Serper.dev only.",
                            status,
                        )
                        return events
                    logger.error(
                        "Eventbrite HTTP %d for %s page %d", status, state, page
                    )
                    break
                except requests.RequestException as exc:
                    logger.error("Eventbrite request error for %s: %s", state, exc)
                    break

                try:
                    data = resp.json()
                except ValueError as exc:
                    logger.error(
                        "Eventbrite returned non-JSON response for %s page %d: %s",
                        state,
                        page,
                        exc,
                    )
                    break

                query_label = f"eventbrite:{STATE_NAMES[state]}"
                for raw in data.get("events", []):
                    item = _normalize_eb_event(raw, query_label)
                    if item is not None:
                        events.append(item)

                pagination = data.get("pagination")
                if pagination is None:
                    logger.warning(
                        "Eventbrite response missing pagination metadata for %s page %d "
                        "— stopping pagination (events may be incomplete)",
                        state,
                        page,
                    )
                    break
                if not pagination.get("has_more_items", False):
                    break
                page += 1

    logger.info("Eventbrite: %d events across %d states", len(events), len(STATE_ORDER))
    return events
