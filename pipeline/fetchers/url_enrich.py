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
import logging
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

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
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
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

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "HISS-Pipeline/1.0 (+https://github.com/distantgeek/home-improvement-search-system)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
)


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


def _extract_json_ld(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        text = tag.string
        if not text:
            continue
        try:
            import json

            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            types = item.get("@type", "")
            if isinstance(types, str):
                types = [types]
            if any(
                t.lower() in ("event", "businessevent", "festival", "saleevent")
                for t in types
            ):
                return item
            place = item.get("location")
            if isinstance(place, dict):
                addr = place.get("address")
                if isinstance(addr, dict) and addr.get("streetAddress"):
                    return item
    return None


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


def _extract_heuristic(text: str) -> dict:
    result: dict = {}
    m = _CITY_STATE_ZIP_RE.search(text)
    if m:
        result["city"] = m.group(1).strip()
        result["state"] = m.group(2)
        result["zip"] = m.group(3)
    elif not result.get("zip"):
        zips = _ZIP_RE.findall(text)
        if zips:
            result["zip"] = zips[0]
    addr_m = _ADDR_LINE_RE.search(text)
    if addr_m:
        result["streetAddress"] = addr_m.group(1).strip()
    return result


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


def _extract_from_soup(soup: BeautifulSoup) -> dict:
    """Extract address fields from a BeautifulSoup document.

    Tries JSON-LD, microdata, and heuristic extraction in order.
    Returns a dict with address fields if found, or an empty dict.
    """
    ld = _extract_json_ld(soup)
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
    fields = _extract_heuristic(text)
    if fields.get("zip") or fields.get("city"):
        return fields
    return {}


def _fetch_and_extract(url: str, timeout: int = _REQUEST_TIMEOUT) -> dict | None:
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
            resp = _SESSION.get(url, timeout=current_timeout, allow_redirects=True)
        except requests.RequestException:
            if attempt == 0:
                logger.debug("URL enrich retrying %s with longer timeout", url[:60])
                continue
            logger.debug("URL enrich fetch failed for %s", url[:80])
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
        except Exception:
            return None
        result = _extract_from_soup(soup)
        if result:
            logger.debug("URL enrich: address hit for %s", url[:80])
            return result
        return {}

    return None


def _render_via_sidecar(url: str) -> dict | None:
    """Send a URL to the Playwright sidecar for JS rendering.

    Returns a dict with address fields on success, an empty dict if the page
    loaded but had no extractable address, or None on sidecar errors.
    """
    if not _SIDECAR_URL:
        return None
    if _is_blocked_url(url):
        return None
    headers = {}
    if _SIDECAR_API_KEY:
        headers["Authorization"] = f"Bearer {_SIDECAR_API_KEY}"
    try:
        resp = _SESSION.post(
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
    except Exception:
        return None
    result = _extract_from_soup(soup)
    if result:
        logger.debug("Sidecar: address hit for %s", url[:80])
        return result
    return {}


def _enrich_one(event: EventItem) -> str:
    """Try to enrich a single event from its URLs.

    Returns a result tag: "enriched", "no_url", "blocked", "fetch_failed",
    "no_address", "no_field_update", or "sidecar_enriched".
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

    had_fetch_error = False
    had_no_address = False

    for url in urls:
        fields = _fetch_and_extract(url)
        if fields is None:
            if _is_blocked_url(url):
                return "blocked"
            had_fetch_error = True
            continue
        if not fields.get("zip") and not fields.get("city"):
            had_no_address = True
            continue
        if _apply_enrichment(event, fields):
            event.sources.append(
                {
                    "url": url,
                    "sourceType": "url_enrich",
                }
            )
            return "enriched"
        return "no_field_update"

    # Event-level retry: if all URLs had fetch errors (no page loaded at all),
    # retry the primary URL once with a longer timeout.
    if had_fetch_error and not had_no_address and event.primary_url:
        fields = _fetch_and_extract(
            event.primary_url, timeout=_REQUEST_TIMEOUT_EVENT_RETRY
        )
        if fields is not None:
            if not fields.get("zip") and not fields.get("city"):
                had_no_address = True
            elif _apply_enrichment(event, fields):
                event.sources.append(
                    {
                        "url": event.primary_url,
                        "sourceType": "url_enrich",
                    }
                )
                return "enriched"
            else:
                return "no_field_update"

    # Sidecar fallback: if static fetches all failed, try Playwright rendering.
    if had_fetch_error and not had_no_address and _SIDECAR_URL and event.primary_url:
        fields = _render_via_sidecar(event.primary_url)
        if fields is not None:
            if not fields.get("zip") and not fields.get("city"):
                return "no_address"
            if _apply_enrichment(event, fields):
                event.sources.append(
                    {
                        "url": event.primary_url,
                        "sourceType": "url_enrich",
                    }
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
