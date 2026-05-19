"""
Port of index.html normalization functions:
  organicsToEvents → organics_to_events
  parseDates       → parse_dates
  inferEventType   → infer_event_type
  normalizeEvent   → normalize_event
"""
from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser as dateutil_parser

from .models import EventItem

# ── Regex constants (ported from JS) ─────────────────────────────────────────

ORGANIC_EVENT_RE = re.compile(
    r"\b(home\s*show|home\s+improvement\s+(show|expo|fair)"
    r"|home\s*(and|&)\s*garden\s+(show|expo)"
    r"|remodeling\s+(show|expo)|renovation\s+(show|expo)"
    r"|outdoor\s+living\s+(show|expo)"
    r"|county\s+fair|state\s+fair|art\s+fair"
    r"|craft\s+(show|fair|festival)|home\s+expo|trade\s+show"
    r"|home\s+garden\s+expo|food\s+festival|wine\s+festival"
    r"|beer\s+festival|seafood\s+festival|strawberry\s+festival"
    r"|harvest\s+festival|fall\s+festival|pumpkin\s+festival"
    r"|oktoberfest|cultural\s+festival|heritage\s+festival"
    r"|community\s+festival|spring\s+festival|summer\s+festival"
    r"|outdoor\s+festival|farm\s+show|agricultural\s+fair)\b",
    re.IGNORECASE,
)

ORGANIC_DATE_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May"
    r"|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?"
    r"|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
    r"\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?,?\s*202\d",
    re.IGNORECASE,
)

ATTENDANCE_RE = re.compile(
    r"\b(?:over\s+|up\s+to\s+|about\s+|approximately\s+|attracts?\s+"
    r"|draws?\s+|expected?\s+)?"
    r"([\d,]+(?:k|\+)?)\s*(?:\+\s*)?(?:attendees?|visitors?|guests?|shoppers?|participants?)\b"
    r"|\battendance\s+(?:of\s+)?(?:over\s+)?([\d,]+(?:k|\+)?)\b",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
SKIP_DOMAIN_RE = re.compile(
    r"\b(wikipedia\.org|instagram\.com|twitter\.com|x\.com"
    r"|tiktok\.com|pinterest\.com|linkedin\.com)\b"
)
_RANGE_SPLIT_RE = re.compile(r"\s*[–\-]\s*")
_YEAR_IN_RANGE_RE = re.compile(r"\b(202\d)\b")
_RANGE_END_RE = re.compile(r"[–\-]\s*(?:(\w+)\s+)?(\d+)(?:,\s*(\d{4}))?")
_COUNTY_FAIR_RE = re.compile(r"\b\w+ county fair\b")

# datetime(date.today().year, 1, 1) is intentionally NOT a module constant — compute it
# inline inside parse_dates so long-running containers survive year rollover.


def organics_to_events(organics: list[dict]) -> list[dict]:
    """Convert Serper organic results to event-shaped dicts (ported from JS)."""
    results = []
    for o in organics:
        link = o.get("link", "")
        if SKIP_DOMAIN_RE.search(link):
            continue
        combined = (o.get("title", "") + " " + o.get("snippet", ""))
        if not ORGANIC_EVENT_RE.search(combined):
            continue

        att_m = ATTENDANCE_RE.search(combined)
        attendance = (
            (att_m.group(1) or att_m.group(2) or "").strip() if att_m else ""
        )

        snippet = o.get("snippet", "")
        email_m = EMAIL_RE.search(snippet)
        phone_m = PHONE_RE.search(snippet)
        contact_parts = []
        if email_m:
            contact_parts.append(email_m.group(0))
        if phone_m:
            contact_parts.append(phone_m.group(0))
        contact = " | ".join(contact_parts)

        title = o.get("title", "")
        title = re.sub(r"\s*[|–]\s*.{0,50}$", "", title)
        title = re.sub(r"\s*:\s*.+$", "", title)
        title = re.sub(
            r"\s*-\s*(tickets?|schedule|dates?|register|event\s+details?)\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        )
        title = title.strip()
        if not title:
            continue

        date_m = ORGANIC_DATE_RE.search(combined)
        results.append(
            {
                "title": title,
                "date": date_m.group(0) if date_m else None,
                "address": snippet,
                "link": link,
                "attendance": attendance,
                "contact": contact,
                "_source_type": "serper_organic",
            }
        )
    return results


def parse_dates(date_input: str | dict | None) -> tuple[str, str]:
    """Return (start_date, end_date) as 'YYYY-MM-DD', or ('', '') on failure.

    Handles:
      - Plain string: "Apr 18 – 19, 2026" or "Sat, Apr 18, 2026"
      - Dict: {"startDate": "...", "when": "..."} (Serper events shape)
      - ISO string: "2026-04-18T10:00:00" (Eventbrite shape)
      - None / empty / unrecognised → ("", "")
    """
    if not date_input:
        return ("", "")

    if isinstance(date_input, str):
        range_str = date_input
        raw_start = date_input
    elif isinstance(date_input, dict):
        range_str = date_input.get("when", "") or date_input.get("startDate", "")
        raw_start = date_input.get("startDate", "") or date_input.get("when", "")
    else:
        return ("", "")

    if not raw_start:
        return ("", "")

    # ISO datetime from Eventbrite (e.g. "2026-04-18T10:00:00") — parse directly
    # before applying range-split logic which would mangle the hyphens.
    if isinstance(raw_start, str) and "T" in raw_start:
        try:
            start = dateutil_parser.parse(raw_start.split("T")[0], default=datetime(date.today().year, 1, 1))
            start_date = start.strftime("%Y-%m-%d")
            return (start_date, start_date)
        except (ValueError, OverflowError, TypeError):
            return ("", "")

    # Strip trailing range " – end" before parsing the start portion
    clean_start = _RANGE_SPLIT_RE.split(raw_start)[0].strip()

    # If start portion has no year, try to borrow one from the full range string
    has_year = bool(re.search(r"\b\d{4}\b", clean_start))
    year_m = _YEAR_IN_RANGE_RE.search(range_str)
    year_fallback = year_m.group(1) if year_m else ""
    if not has_year and year_fallback:
        clean_start = f"{clean_start}, {year_fallback}"

    try:
        start = dateutil_parser.parse(clean_start, default=datetime(date.today().year, 1, 1))
        start_date = start.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return ("", "")

    # Parse end date from range notation: "Apr 18 – 19" or "Apr 18 – May 3, 2026"
    m = _RANGE_END_RE.search(range_str)
    if m:
        month = m.group(1) or start.strftime("%b")
        day = m.group(2)
        year = m.group(3) or str(start.year)
        try:
            end = dateutil_parser.parse(f"{month} {day}, {year}", default=datetime(date.today().year, 1, 1))
            if end >= start:
                return (start_date, end.strftime("%Y-%m-%d"))
        except (ValueError, OverflowError):
            pass

    return (start_date, start_date)


def infer_event_type(query: str, title: str) -> str:
    """Classify an event into one of the eight event type categories."""
    s = (query + " " + title).lower()
    if "state fair" in s:
        return "State Fair"
    if "county fair" in s or _COUNTY_FAIR_RE.search(s):
        return "County Fair"
    if any(k in s for k in ("harvest festival", "fall festival", "pumpkin festival", "oktoberfest")):
        return "Fall Festival"
    if any(k in s for k in ("food festival", "wine festival", "beer festival", "seafood", "strawberry festival", "taste of")):
        return "Food Festival"
    if any(k in s for k in ("cultural festival", "heritage festival", "community festival", "spring festival", "summer festival", "outdoor festival")):
        return "Community Festival"
    if "garden" in s or "outdoor living" in s:
        return "Home & Garden"
    if "art" in s or "craft" in s:
        return "Art & Craft"
    return "Home Show"


_ZIP_RE = re.compile(r"\b(\d{5})\b")
_GOV_URL_RE = re.compile(r"\.(gov|us)\b", re.IGNORECASE)
_PARKS_URL_RE = re.compile(r"parks|recreation|tourism|countymd", re.IGNORECASE)


def normalize_event(
    evt: dict,
    source_query: str,
    search_state: str | None,
) -> EventItem | None:
    """Normalize a raw Serper or Eventbrite event dict into an EventItem.

    The returned item has county/city empty; call enrich() to fill those in.
    """
    name = (evt.get("title", "") or "").strip()
    if not name:
        return None

    start_date, end_date = parse_dates(evt.get("date"))

    addr_raw = evt.get("address", "")
    if isinstance(addr_raw, list):
        addr_full = ", ".join(addr_raw)
        venue = addr_raw[0] if addr_raw else ""
    else:
        addr_full = addr_raw or ""
        venue = ""

    zip_m = _ZIP_RE.search(addr_full)
    zip_code = zip_m.group(1) if zip_m else ""

    source_type = evt.get("_source_type", "serper_organic")

    url = evt.get("link", "")
    current_year = date.today().year
    page_score = (
        (2 if str(current_year) in name else 0)
        + (-1 if _GOV_URL_RE.search(url) else 0)
        + (-1 if _PARKS_URL_RE.search(url) else 0)
    )

    return EventItem(
        name=name,
        start_date=start_date,
        end_date=end_date,
        venue=venue,
        city="",
        state=search_state or "",
        county="",
        county_full="",
        zip=zip_code,
        event_type=infer_event_type(source_query, name),
        primary_url=url,
        source_type=source_type,
        source_queries=[source_query],
        attendance=evt.get("attendance", ""),
        contact=evt.get("contact", ""),
        page_score=page_score,
        addr_full=addr_full,
    )
