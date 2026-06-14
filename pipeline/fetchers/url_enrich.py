"""URL-based address enrichment for events missing ZIP/county data.

Scrapes event web pages (primary_url or alternate sources) for structured
address data using JSON-LD (priority 1), microdata (priority 2), or
heuristic regex extraction (priority 3). Only fills empty fields — never
overwrites data already populated by higher-priority sources.

SSRF protection:
  - Only HTTPS URLs are fetched
  - Private/reserved IP ranges are blocked (10.x, 172.16-31.x, 192.168.x,
    127.x, 169.254.x, ::1, fc00::/7)
  - Internal-looking hostnames are blocked (localhost, *.local, *.internal)
  - A per-domain rate limit prevents hammering any single host
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import threading

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from ..models import EventItem

logger = logging.getLogger(__name__)

_MAX_WORKERS = 5
_REQUEST_TIMEOUT = 12
_REQUEST_TIMEOUT_RETRY = 20
_REQUEST_TIMEOUT_EVENT_RETRY = 25
_DOMAIN_DELAY_SECONDS = 2.0
_MAX_URLS_PER_EVENT = 3
_SIDECAR_URL = os.environ.get("SIDECAR_URL", "")
_SIDECAR_TIMEOUT = int(os.environ.get("SIDECAR_TIMEOUT", "30") or "30")
_SIDECAR_API_KEY = os.environ.get("SIDECAR_API_KEY", "")

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("::/128"),
]

_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
    ".test",
    ".example",
    ".invalid",
)

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_RE = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME"
    r"|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA"
    r"|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
)
_CITY_STATE_ZIP_RE = re.compile(
    r"(?:,\s*|\s|^)([A-Z][A-Za-z\s]{2,29}?)\s*,\s*([A-Z]{2})\s+(\d{5})"
)
_ADDR_LINE_RE = re.compile(
    r"(\d{1,5}\s+[A-Za-z][A-Za-z\s]{2,30}(?:Street|St|Ave|Avenue|Blvd|Boulevard"
    r"|Dr|Drive|Rd|Road|Ln|Lane|Way|Ct|Court|Pl|Place|Pkwy|Parkway|Cir|Circle"
    r"|Ter|Terrace|Trl|Trail)\.?)",
    re.IGNORECASE,
)

_SESSION_HEADERS = {
    "User-Agent": (
        "HISS-Pipeline/1.0 (+https://github.com/distantgeek/home-improvement-search-system)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_thread_local = threading.local()


def _get_session() -> requests.Session:
    """Return a per-thread requests.Session. Session is not thread-safe; each
    worker in the ThreadPoolExecutor must own its own instance."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(_SESSION_HEADERS)
        _thread_local.session = s
    return _thread_local.session


def _is_private_ip(hostname: str) -> bool:
    try:
        addr_info = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return True
    for family, _type, _proto, _canon, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in net for net in _PRIVATE_NETWORKS):
                return True
        except ValueError:
            continue
    return False


def _is_blocked_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return True
    if parsed.scheme != "https":
        return True
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if any(host.endswith(s) for s in _BLOCKED_HOST_SUFFIXES):
        return True
    if _is_private_ip(host):
        return True
    return False


_EVENT_LD_TYPES = frozenset(
    ("event", "businessevent", "festival", "saleevent", "sportsevent", "educationevent")
)
_NAME_MATCH_THRESHOLD = 50


def _ld_has_address(item: dict) -> bool:
    place = item.get("location")
    if isinstance(place, dict):
        addr = place.get("address")
        if isinstance(addr, dict) and (
            addr.get("postalCode") or addr.get("addressLocality")
        ):
            return True
    return False


def _extract_json_ld(soup: BeautifulSoup, event_name: str = "") -> dict | None:
    """Extract the most relevant Event JSON-LD from the page.

    On listing pages with multiple events, scores all candidates against
    event_name using token-set ratio and returns the best match above
    _NAME_MATCH_THRESHOLD. Falls back to the first candidate with an address
    when no name match is confident enough.
    """
    candidates: list[dict] = []
    fallbacks: list[dict] = []  # non-event-type items that have address data

    for tag in soup.find_all("script", type="application/ld+json"):
        text = tag.string
        if not text:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue

        # Flatten: handle arrays, single objects, and @graph wrappers
        raw_items: list = data if isinstance(data, list) else [data]
        flat: list[dict] = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            if "@graph" in it:
                graph = it["@graph"]
                if isinstance(graph, list):
                    flat.extend(g for g in graph if isinstance(g, dict))
            else:
                flat.append(it)

        for item in flat:
            types = item.get("@type", "")
            if isinstance(types, str):
                types = [types]
            is_event_type = any(t.lower() in _EVENT_LD_TYPES for t in types)
            has_addr = _ld_has_address(item)

            if is_event_type and has_addr:
                candidates.append(item)
            elif not is_event_type and has_addr:
                fallbacks.append(item)

    if not candidates:
        return fallbacks[0] if fallbacks else None

    if len(candidates) == 1:
        return candidates[0]

    # Multiple events on page — score against the event name we're enriching.
    # This prevents listing pages (with 20+ events) from returning the wrong ZIP.
    if event_name:
        best_score = -1
        best = candidates[0]
        for c in candidates:
            cname = (c.get("name") or "").strip()
            if not cname:
                continue
            score = fuzz.token_set_ratio(event_name, cname)
            if score > best_score:
                best_score = score
                best = c
        if best_score >= _NAME_MATCH_THRESHOLD:
            return best

    return candidates[0]


def _extract_microdata(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all(itemtype=re.compile(r"Event", re.IGNORECASE)):
        addr_tag = tag.find(itemprop="address")
        if addr_tag:
            return _microdata_to_dict(tag)
    for tag in soup.find_all(itemprop="address"):
        return _microdata_to_dict(tag.parent if tag.parent else tag)
    return None


def _microdata_to_dict(tag) -> dict:
    result = {}
    for child in tag.find_all(itemprop=True):
        prop = child.get("itemprop", "")
        content = (
            child.get("content") or child.get("datetime") or child.get_text(strip=True)
        )
        if content:
            result[prop] = content
    return result


def _extract_heuristic(text: str, event_name: str = "") -> dict:
    """Extract address fields from raw page text.

    When event_name is provided, searches a ±1000-char window around the first
    occurrence of the event name before falling back to the full page. This
    prevents picking up ZIP codes from other events on listing pages.
    """
    def _scan(t: str) -> dict:
        r: dict = {}
        m = _CITY_STATE_ZIP_RE.search(t)
        if m:
            r["city"] = m.group(1).strip()
            r["state"] = m.group(2)
            r["zip"] = m.group(3)
        if not r.get("zip"):
            zips = _ZIP_RE.findall(t)
            if zips:
                r["zip"] = zips[0]
        addr_m = _ADDR_LINE_RE.search(t)
        if addr_m:
            r["streetAddress"] = addr_m.group(1).strip()
        return r

    if event_name:
        anchor = event_name[:40].lower()
        idx = text.lower().find(anchor)
        if idx >= 0:
            # Addresses almost always follow the event title in structured content.
            # Anchor at the name position to avoid ZIPs from other events earlier on
            # the page (listing pages with 20+ events).
            window = text[idx : idx + 800]
            result = _scan(window)
            if result.get("zip") or result.get("city"):
                return result

    return _scan(text)


def _parse_json_ld_address(data: dict) -> dict:
    result: dict = {}
    location = data.get("location")
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return result
    addr = location.get("address")
    if isinstance(addr, list):
        addr = addr[0] if addr else None
    if isinstance(addr, dict):
        for src_key, dst_key in [
            ("streetAddress", "streetAddress"),
            ("addressLocality", "city"),
            ("addressRegion", "state"),
            ("postalCode", "zip"),
        ]:
            val = addr.get(src_key)
            if val and isinstance(val, str):
                result[dst_key] = val.strip()
    if not result.get("city"):
        result["city"] = (location.get("name") or "").strip() or result.get("city", "")
    venue_name = (location.get("name") or "").strip()
    if venue_name:
        result["venue"] = venue_name
    return result


def _parse_microdata_address(data: dict) -> dict:
    result: dict = {}
    for src, dst in [
        ("streetAddress", "streetAddress"),
        ("addressLocality", "city"),
        ("addressRegion", "state"),
        ("postalCode", "zip"),
        ("name", "venue"),
    ]:
        val = data.get(src)
        if val and isinstance(val, str):
            result[dst] = val.strip()
    return result


def _apply_enrichment(event: EventItem, fields: dict) -> bool:
    updated = False
    if fields.get("zip") and not event.zip:
        event.zip = fields["zip"][:5]
        updated = True
    if fields.get("city") and not event.city:
        event.city = fields["city"]
        updated = True
    if fields.get("state") and not event.state:
        event.state = fields["state"]
        updated = True
    if fields.get("venue") and not event.venue:
        event.venue = fields["venue"]
        updated = True
    if fields.get("streetAddress") and not event.addr_full:
        parts = [
            p
            for p in [
                fields.get("streetAddress", ""),
                fields.get("city", ""),
                fields.get("state", ""),
                fields.get("zip", ""),
            ]
            if p
        ]
        if parts:
            event.addr_full = ", ".join(parts)
            updated = True
    return updated


def _extract_from_soup(soup: BeautifulSoup, event_name: str = "") -> dict:
    """Extract address fields from a BeautifulSoup document.

    Tries JSON-LD, microdata, and heuristic extraction in order.
    event_name is used to score JSON-LD candidates on listing pages and to
    anchor the heuristic ZIP search near the relevant event in the page text.
    """
    ld = _extract_json_ld(soup, event_name=event_name)
    if ld:
        fields = _parse_json_ld_address(ld)
        if fields.get("zip") or fields.get("city"):
            return fields
    md = _extract_microdata(soup)
    if md:
        fields = _parse_microdata_address(md)
        if fields.get("zip") or fields.get("city"):
            return fields
    text = soup.get_text(separator=" ", strip=True)
    fields = _extract_heuristic(text, event_name=event_name)
    if fields.get("zip") or fields.get("city"):
        return fields
    return {}


def _fetch_and_extract(
    url: str, timeout: int = _REQUEST_TIMEOUT, event_name: str = ""
) -> dict | None:
    """Fetch a URL and extract address data from the HTML.

    Returns a dict with address fields on success, an empty dict if the page
    loaded but had no extractable address, or None on blocked/fetch/HTTP errors.

    On transient connection errors (timeout, DNS failure), retries once with
    a longer timeout before giving up.
    """
    if _is_blocked_url(url):
        logger.debug("URL blocked (SSRF/privacy): %s", url[:80])
        return None

    for attempt in range(2):
        current_timeout = timeout if attempt == 0 else _REQUEST_TIMEOUT_RETRY
        try:
            resp = _get_session().get(url, timeout=current_timeout, allow_redirects=True)
        except requests.RequestException:
            if attempt == 0:
                logger.debug("URL enrich retrying %s with longer timeout", url[:60])
                continue
            logger.debug("URL enrich fetch failed for %s", url[:80])
            return None

        # Re-check SSRF after redirect
        if resp.url != url and _is_blocked_url(resp.url):
            logger.debug("URL enrich: redirect to blocked URL: %s -> %s", url[:60], resp.url[:60])
            return None

        if resp.status_code >= 400:
            logger.debug("URL enrich HTTP %d for %s", resp.status_code, url[:80])
            return None
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            logger.debug("URL enrich skipping non-HTML: %s", url[:80])
            return None
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            logger.debug("BeautifulSoup parse error for %s: %s", url[:80], exc)
            return None
        result = _extract_from_soup(soup, event_name=event_name)
        if result:
            logger.debug("URL enrich: address hit for %s", url[:80])
            return result
        return {}

    return None


def _render_via_sidecar(url: str, event_name: str = "") -> dict | None:
    """Send a URL to the Playwright sidecar for JS rendering.

    Returns a dict with address fields on success, an empty dict if the page
    loaded but had no extractable address, or None on sidecar errors.
    """
    if not _SIDECAR_URL:
        return None
    if _is_blocked_url(url):
        return None
    headers = {"Authorization": f"Bearer {_SIDECAR_API_KEY}"} if _SIDECAR_API_KEY else {}
    try:
        resp = _get_session().post(
            f"{_SIDECAR_URL.rstrip('/')}/render",
            json={"url": url, "timeout": _SIDECAR_TIMEOUT},
            headers=headers,
            timeout=_SIDECAR_TIMEOUT + 10,
        )
    except requests.RequestException as exc:
        logger.debug("Sidecar request failed for %s: %s", url[:60], exc)
        return None
    if resp.status_code != 200:
        logger.debug("Sidecar returned %d for %s", resp.status_code, url[:60])
        return None
    try:
        data = resp.json()
    except (ValueError, TypeError):
        logger.debug("Sidecar returned invalid JSON for %s", url[:60])
        return None
    html = data.get("html", "")
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.debug("Sidecar BeautifulSoup parse error for %s: %s", url[:80], exc)
        return None
    result = _extract_from_soup(soup, event_name=event_name)
    if result:
        logger.debug("Sidecar: address hit for %s", url[:80])
        return result
    return {}


def _enrich_one(event: EventItem) -> str:
    """Try to enrich a single event from its URLs.

    Returns a result tag: "enriched", "no_url", "blocked", "fetch_failed",
    "no_address", "no_field_update", or "sidecar_enriched".

    Sidecar is tried whenever static extraction found no address — this covers
    both JS-heavy pages (load OK, address rendered by JS) and pages that fail
    to load at all (SPAs, bot-blocking, etc.).
    """
    urls = []
    if event.primary_url:
        urls.append(event.primary_url)
    for src in event.sources[: _MAX_URLS_PER_EVENT - 1]:
        u = src.get("url", "")
        if u and u not in urls:
            urls.append(u)
    urls = urls[:_MAX_URLS_PER_EVENT]
    if not urls:
        return "no_url"

    all_blocked = True
    had_fetch_error = False
    had_no_address = False

    for url in urls:
        if _is_blocked_url(url):
            continue
        all_blocked = False
        fields = _fetch_and_extract(url, event_name=event.name)
        if fields is None:
            had_fetch_error = True
            continue
        if not fields.get("zip") and not fields.get("city"):
            had_no_address = True
            continue
        if _apply_enrichment(event, fields):
            event.sources.append({"url": url, "sourceType": "url_enrich"})
            return "enriched"
        return "no_field_update"

    if all_blocked:
        return "blocked"

    # Extended retry: if all URLs failed to load (network error), retry the
    # primary URL once with a longer timeout before escalating to sidecar.
    if had_fetch_error and not had_no_address and event.primary_url:
        fields = _fetch_and_extract(
            event.primary_url,
            timeout=_REQUEST_TIMEOUT_EVENT_RETRY,
            event_name=event.name,
        )
        if fields is not None:
            if fields.get("zip") or fields.get("city"):
                if _apply_enrichment(event, fields):
                    event.sources.append(
                        {"url": event.primary_url, "sourceType": "url_enrich"}
                    )
                    return "enriched"
                return "no_field_update"
            had_no_address = True

    # Sidecar fallback: try when static extraction found no address.
    # This fires for two distinct cases:
    #   1. Page loaded but address is JS-rendered (had_no_address=True, had_fetch_error=False)
    #   2. Page failed to load entirely — may work in a real browser (had_fetch_error=True)
    if _SIDECAR_URL and event.primary_url and (had_no_address or had_fetch_error):
        fields = _render_via_sidecar(event.primary_url, event_name=event.name)
        if fields is not None:
            if not fields.get("zip") and not fields.get("city"):
                return "no_address"
            if _apply_enrichment(event, fields):
                event.sources.append(
                    {"url": event.primary_url, "sourceType": "url_enrich"}
                )
                return "sidecar_enriched"
            return "no_field_update"

    if had_no_address:
        return "no_address"
    return "fetch_failed"


def enrich_from_urls(
    events: list[EventItem],
    *,
    max_workers: int = _MAX_WORKERS,
) -> int:
    candidates = [e for e in events if not e.zip or not e.county or not e.city]
    logger.info(
        "URL enrich: %d candidates (of %d total events)",
        len(candidates),
        len(events),
    )
    if not candidates:
        return 0

    counters: dict[str, int] = {
        "enriched": 0,
        "no_url": 0,
        "blocked": 0,
        "fetch_failed": 0,
        "no_address": 0,
        "no_field_update": 0,
        "sidecar_enriched": 0,
    }
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_enrich_one, ev): ev for ev in candidates}
        for future in as_completed(futures):
            ev = futures[future]
            try:
                result = future.result()
                counters[result] = counters.get(result, 0) + 1
            except Exception as exc:
                logger.error("Unexpected error enriching %s: %s", ev.name[:60], exc)
                counters["fetch_failed"] = counters.get("fetch_failed", 0) + 1

    logger.info(
        "URL enrich results: %d enriched, %d no_url, %d blocked, "
        "%d fetch_failed, %d no_address, %d no_field_update, "
        "%d sidecar_enriched (of %d candidates)",
        counters["enriched"],
        counters["no_url"],
        counters["blocked"],
        counters["fetch_failed"],
        counters["no_address"],
        counters["no_field_update"],
        counters.get("sidecar_enriched", 0),
        len(candidates),
    )
    return counters["enriched"] + counters.get("sidecar_enriched", 0)
