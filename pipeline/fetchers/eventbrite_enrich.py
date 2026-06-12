"""Eventbrite per-event API enrichment.

After Serper.dev discovery, events whose primary_url or alternate URLs point to
Eventbrite are enriched with structured address data (venue, city, state, ZIP)
from the Eventbrite Event Retrieval API (/v3/events/{id}/).

This is distinct from the Discovery API (enterprise-only, handled in
eventbrite.py). The retrieval endpoint is available on the free OAuth tier.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from ..models import EventItem

logger = logging.getLogger(__name__)

_EVENT_API_URL = "https://www.eventbriteapi.com/v3/events/{id}/"
_ALLOWED_HOSTS = frozenset({"www.eventbrite.com", "eventbrite.com"})

# Matches /e/<optional-slug>-<id> where id is 5–20 digits
_ID_RE = re.compile(r"/e/(?:[^/?#]*?-)?(\d{5,20})(?:[/?#]|$)")

# Pure function words only — domain terms like "home", "show", "fair" are
# intentionally kept so short event names ("Home Show", "County Fair") still
# produce tokens that can match. See _validate_response for the empty-set fallback.
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "in",
        "at",
        "for",
        "to",
        "with",
    }
)

_MAX_WORKERS = 5  # conservative — free tier allows 2 000 calls/hour


# ── URL validation ──────────────────────────────────────────────────────────


def extract_eventbrite_id(url: str) -> str | None:
    """Return the Eventbrite numeric event ID from a URL, or None if invalid.

    Validates:
    - Scheme is https (rejects http and non-URLs)
    - Host is exactly eventbrite.com or www.eventbrite.com (no lookalikes)
    - Path matches the /e/<slug>-<id> pattern
    - Extracted ID is 5–20 decimal digits
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    if parsed.netloc not in _ALLOWED_HOSTS:
        return None
    m = _ID_RE.search(parsed.path)
    if not m:
        return None
    event_id = m.group(1)
    if not event_id.isdigit() or not (5 <= len(event_id) <= 20):
        return None
    return event_id


# ── Response validation ─────────────────────────────────────────────────────


def _name_tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"\w+", text.lower())
        if len(w) > 3 and w not in _STOP_WORDS
    }


def _validate_response(raw: dict, expected_id: str, event: EventItem) -> bool:
    """Confirm the API response is for the correct event before applying changes.

    Checks:
    1. Response ID matches the ID we requested.
    2. Event is not cancelled.
    3. At least one significant name token overlaps with the locally-known name.
    """
    if str(raw.get("id", "")) != expected_id:
        logger.warning(
            "Eventbrite ID mismatch: requested=%s got=%s (url=%s)",
            expected_id,
            raw.get("id"),
            event.primary_url,
        )
        return False

    if raw.get("status") == "cancelled":
        logger.debug("Skipping cancelled Eventbrite event %s", expected_id)
        return False

    api_name = (raw.get("name") or {}).get("text", "")
    api_tokens = _name_tokens(api_name)
    local_tokens = _name_tokens(event.name)
    # When both names reduce to empty token sets (very short/generic names) the
    # ID match above is sufficient — don't reject on a vacuous intersection check.
    if api_tokens and local_tokens and not (api_tokens & local_tokens):
        logger.warning(
            "Eventbrite name mismatch — skipping enrichment for event %s "
            "(api=%r local=%r)",
            expected_id,
            api_name[:80],
            event.name[:80],
        )
        return False

    return True


# ── Field update ────────────────────────────────────────────────────────────


def _apply_enrichment(event: EventItem, raw: dict) -> None:
    """Overwrite address fields on the event with structured Eventbrite data.

    Only overwrites non-empty values so a partial Eventbrite response can't
    blank out fields we already have from Serper.
    """
    venue_obj = raw.get("venue") or {}
    address = venue_obj.get("address") or {}

    zip_code = (address.get("postal_code") or "")[:5]
    city = address.get("city") or ""
    region = address.get("region") or ""
    venue_name = venue_obj.get("name") or ""
    address_1 = address.get("address_1") or ""

    if zip_code:
        event.zip = zip_code
    if city:
        event.city = city
    if region:
        event.state = region
    if venue_name:
        event.venue = venue_name

    # Rebuild addr_full so Enricher.enrich() receives the best possible input
    parts = [p for p in [venue_name, address_1, city, region, zip_code] if p]
    if parts:
        event.addr_full = ", ".join(parts)


# ── Per-event fetch ─────────────────────────────────────────────────────────


def _enrich_one(event: EventItem, event_id: str, api_key: str) -> bool:
    """Fetch and apply structured address data for a single event.

    Each call opens its own Session so this function is safe to run from
    multiple threads without coordination.

    Returns True if the event was updated.
    """
    url = _EVENT_API_URL.format(id=event_id)
    try:
        with requests.Session() as session:
            resp = session.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                params={"expand": "venue"},
                timeout=10,
            )
    except requests.RequestException as exc:
        logger.warning("Eventbrite enrich request failed for %s: %s", event_id, exc)
        return False

    if resp.status_code in (401, 403, 404):
        # 401 = token lacks retrieval scope (free tier may not include it)
        # 403 = private event  404 = deleted/unpublished
        logger.debug(
            "Eventbrite event %s unavailable (HTTP %d)", event_id, resp.status_code
        )
        return False
    if not resp.ok:
        logger.warning(
            "Eventbrite enrich HTTP %d for event %s", resp.status_code, event_id
        )
        return False

    try:
        raw = resp.json()
    except ValueError as exc:
        logger.warning("Eventbrite non-JSON response for event %s: %s", event_id, exc)
        return False

    if not _validate_response(raw, event_id, event):
        return False

    _apply_enrichment(event, raw)
    event.sources.append(
        {
            "url": _EVENT_API_URL.format(id=event_id),
            "sourceType": "eventbrite_enrich",
        }
    )
    logger.debug("Enriched event %s (%s) from Eventbrite", event_id, event.name[:60])
    return True


# ── Public entry point ──────────────────────────────────────────────────────


def enrich_from_urls(
    events: list[EventItem],
    api_key: str,
    *,
    max_workers: int = _MAX_WORKERS,
) -> int:
    """Enrich events that have Eventbrite URLs with structured address data.

    Scans primary_url and alternate sources on every event, validates each URL
    before calling the API, and applies venue/address/ZIP data only where the
    response passes all validation checks.

    Deduplicates by Eventbrite event ID so each API call is made at most once.

    Returns the count of events successfully enriched.
    """
    seen_ids: set[str] = set()
    candidates: list[tuple[EventItem, str]] = []

    for event in events:
        event_id = extract_eventbrite_id(event.primary_url)
        if event_id and event_id not in seen_ids:
            seen_ids.add(event_id)
            candidates.append((event, event_id))
            continue
        # Also check alternate URLs accumulated by the dedup step
        for src in event.sources:
            alt_id = extract_eventbrite_id(src.get("url", ""))
            if alt_id and alt_id not in seen_ids:
                seen_ids.add(alt_id)
                candidates.append((event, alt_id))
                break

    logger.info(
        "Eventbrite enrich: %d candidates from %d events",
        len(candidates),
        len(events),
    )
    if not candidates:
        return 0

    enriched = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_enrich_one, ev, eid, api_key): (ev, eid)
            for ev, eid in candidates
        }
        for future in as_completed(futures):
            _ev, eid = futures[future]
            try:
                if future.result():
                    enriched += 1
            except Exception as exc:
                logger.error("Unexpected error enriching event %s: %s", eid, exc)

    logger.info(
        "Eventbrite enrich: updated %d of %d candidates", enriched, len(candidates)
    )
    return enriched
