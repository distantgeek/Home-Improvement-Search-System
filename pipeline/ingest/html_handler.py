"""
FestivalNet My List HTML ingest handler.

Parses browser-saved FestivalNet member "My List" print-view HTML pages
and extracts structured event data into EventItem objects.

Usage: save the FestivalNet My List page in a browser (Ctrl+S →
"Web Page, HTML Only"), then run:
    python3 -m pipeline.run --ingest-file path/to/page.html
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from pipeline.constants import EVENT_TYPES
from pipeline.normalize import infer_event_type, parse_dates

if TYPE_CHECKING:
    from pipeline.models import EventItem

logger = logging.getLogger(__name__)

_SOURCE_TYPE = "festivalnet"
_PAGE_SCORE = 3
_TARGET_STATES = frozenset({"MD", "VA", "PA", "NJ", "DE", "DC"})

_EMAIL_SCRIPT_RE = re.compile(r"unescape\('([^']+)'\)")
_MAILTO_RE = re.compile(r"mailto:([^\"'>\s]+)")
_ZIP_RE = re.compile(r"\b(\d{5})\b")

_FN_EVENT_TYPE_MAP: dict[str, str] = {
    "arts & crafts show": "Art & Craft",
    "festival/event/fair": "Community Festival",
    "music & art festival": "Community Festival",
    "food festival": "Food Festival",
    "state fair": "State Fair",
    "county fair": "County Fair",
    "home & garden show": "Home & Garden",
    "home show": "Home Show",
    "trade show": "Home Show",
    "fall festival": "Fall Festival",
    "community festival": "Community Festival",
    "craft show": "Art & Craft",
    "audio & video show": "Home Show",
}


def _decode_email(script_text: str) -> str:
    m = _EMAIL_SCRIPT_RE.search(script_text)
    if not m:
        return ""
    decoded = unquote(m.group(1))
    mail_m = _MAILTO_RE.search(decoded)
    if mail_m:
        return mail_m.group(1)
    email_match = re.search(
        r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
        decoded,
    )
    if email_match:
        return email_match.group(0)
    return ""


def _get_field(table: Tag, label: str) -> Tag | None:
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        font = tds[0].find("font", class_="font-color")
        if font and label in font.get_text(strip=True):
            return tr
    return None


def _field_value(table: Tag, label: str) -> str:
    tr = _get_field(table, label)
    if not tr:
        return ""
    tds = tr.find_all("td")
    if len(tds) < 2:
        return ""
    val_font = tds[1].find("font", class_="fieldValueProS")
    if val_font:
        text = val_font.get_text(separator=" ", strip=True)
    else:
        text = tds[1].get_text(separator=" ", strip=True)
    return text


def _field_value_font(table: Tag, label: str) -> Tag | None:
    tr = _get_field(table, label)
    if not tr:
        return None
    tds = tr.find_all("td")
    if len(tds) < 2:
        return None
    return tds[1].find("font", class_="fieldValueProS")


def _field_email(table: Tag, label: str) -> str:
    tr = _get_field(table, label)
    if not tr:
        return ""
    tds = tr.find_all("td")
    if len(tds) < 2:
        return ""
    script_el = tds[1].find("script")
    if script_el and script_el.string:
        return _decode_email(script_el.string)
    font_el = tds[1].find("font", class_="fieldValueProS")
    if font_el:
        text = font_el.get_text(strip=True)
        return text if "@" in text else ""
    return ""


def _extract_web_url(table: Tag) -> str:
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        for i, td in enumerate(tds):
            label_font = td.find("font", class_="font-color")
            if not label_font:
                continue
            label_text = label_font.get_text(strip=True)
            if "Web:" not in label_text:
                continue
            for j in range(i, len(tds)):
                for a in tds[j].find_all("a"):
                    href = a.get("href", "")
                    if (
                        href
                        and href.startswith("http")
                        and "festivalnet.com" not in href
                        and "mailto:" not in href
                        and "javascript:" not in href
                        and "google" not in href
                    ):
                        return href
    return ""


def _parse_event_table(table: Tag) -> EventItem | None:
    from pipeline.models import EventItem

    main_cell = table.find("td", colspan=lambda v: v and "3" in str(v))
    if not main_cell:
        return None

    name_el = main_cell.find("h1", itemprop="name")
    name = name_el.get_text(strip=True) if name_el else ""
    if not name:
        return None

    date_span = main_cell.find("span", class_="bold")
    date_text = date_span.get_text(strip=True) if date_span else ""
    start_date, end_date = parse_dates(date_text)

    venue = ""
    city = ""
    state_code = ""
    zip_code = ""

    location_div = main_cell.find_all("div")
    for div in location_div:
        font = div.find("font")
        if not font:
            continue
        links = font.find_all("a")
        if not links:
            continue

        raw_text = font.get_text(separator=" ", strip=True)
        zip_m = _ZIP_RE.search(raw_text)
        if zip_m:
            zip_code = zip_m.group(1)
            text_before_zip = raw_text.split(zip_code)[0]

            parts = [p.strip() for p in text_before_zip.split(",") if p.strip()]
            if len(parts) >= 3:
                venue = parts[0]
                city = parts[1]
                state_code = parts[2]
            elif len(parts) == 2:
                venue = parts[0]
                city = parts[1]
            break

    if not state_code:
        for link in div.find_all("a") if location_div else main_cell.find_all("a"):
            href = link.get("href", "")
            if "state_local=" in href:
                state_m = re.search(r"state_local=(\w{2})", href)
                if state_m:
                    state_code = state_m.group(1).upper()
                    break
        if not state_code:
            for div in main_cell.find_all("div"):
                font = div.find("font")
                if font:
                    for a in font.find_all("a"):
                        href = a.get("href", "")
                        if "state_local=" in href:
                            state_m = re.search(r"state_local=(\w{2})", href)
                            if state_m:
                                state_code = state_m.group(1).upper()
                                break

    event_addr = _field_value(table, "Event Address:")
    if not venue and event_addr:
        venue = event_addr

    combined_addr = ", ".join(p for p in [venue, city, event_addr] if p)

    fn_type_raw = _field_value(table, "Event Type:")
    fn_type_raw = re.sub(r"\s*…\s*$", "", fn_type_raw)
    fn_type_clean = fn_type_raw.strip().lower()
    event_type = ""
    for fn_key, hiss_type in _FN_EVENT_TYPE_MAP.items():
        if fn_key in fn_type_clean:
            event_type = hiss_type
            break
    if not event_type:
        event_type = infer_event_type(fn_type_raw, name)
        if event_type == "Home Show":
            for t in EVENT_TYPES:
                if t.lower() in fn_type_clean:
                    event_type = t
                    break

    attendance = _field_value(table, "Attendance #:")
    attendance = re.sub(r"\s*$", "", attendance)

    web_url = _extract_web_url(table)

    main_email = _field_email(table, "Main Email:")
    contact_parts = []
    if main_email:
        contact_parts.append(main_email)
    for label in (
        "Show Director:",
        "Exhibit Director:",
        "Food Director:",
        "Entertainment:",
    ):
        email_val = _field_email(table, label)
        if email_val and email_val != "na":
            contact_parts.append(email_val)
    contact = " | ".join(dict.fromkeys(contact_parts))

    status_div = main_cell.find("div", class_="event-status")
    status_text = status_div.get_text(strip=True) if status_div else ""
    status_clean = status_text.replace("Status:", "").strip()

    description = _field_value(table, "Description:")
    if not description:
        desc_tr = _get_field(table, "Description")
        if desc_tr:
            tds = desc_tr.find_all("td")
            if len(tds) >= 2:
                description = tds[1].get_text(separator=" ", strip=True)

    primary_url = web_url or ""
    sources = []
    if primary_url:
        sources.append({"url": primary_url, "sourceType": _SOURCE_TYPE})

    return EventItem(
        name=name,
        start_date=start_date,
        end_date=end_date or start_date,
        venue=venue,
        city=city,
        state=state_code,
        county="",
        county_full="",
        zip=zip_code,
        event_type=event_type,
        primary_url=primary_url,
        source_type=_SOURCE_TYPE,
        source_queries=[f"festivalnet:{state_code or 'unknown'}"],
        sources=sources,
        attendance=attendance,
        contact=contact,
        page_score=_PAGE_SCORE,
        addr_full=combined_addr,
    )


def parse_html(path: Path) -> list[EventItem]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    events = []

    printed_pages = soup.find("div", class_="printed-pages")
    if not printed_pages:
        tables = soup.find_all("table", class_="ProMembersSearchFullDetailsTable")
    else:
        tables = printed_pages.find_all(
            "table", class_="ProMembersSearchFullDetailsTable"
        )

    logger.info("Found %d event tables in %s", len(tables), path.name)

    for table in tables:
        event = _parse_event_table(table)
        if event and event.state in _TARGET_STATES:
            events.append(event)
        elif event:
            logger.debug(
                "Skipping non-target state event: %s (%s)", event.name, event.state
            )

    logger.info(
        "HTML: parsed %d events from %s (%d tables total, %d non-target skipped)",
        len(events),
        path.name,
        len(tables),
        len(tables) - len(events),
    )
    return events
