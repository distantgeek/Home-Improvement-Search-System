"""Three-tier county/ZIP enrichment (ported from index.html normalizeEvent)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .constants import COUNTIES, STATE_ORDER
from .models import EventItem

logger = logging.getLogger(__name__)

_SUFFIX_RE = re.compile(
    r"\s+(County|Borough|Township|Parish|District)\s*$", re.IGNORECASE
)
_CITY_SUFFIX_RE = re.compile(r"\s+city\s*$", re.IGNORECASE)
_STATE_ZIP_RE = re.compile(r",?\s*[A-Z]{2}\s*\d{5}(-\d{4})?\s*$")
_TRAILING_COMMA_RE = re.compile(r",\s*$")


def _strip_suffix(name: str) -> str:
    """Remove trailing County/Borough/etc. suffix.

    Handles Census naming conventions:
    - "Frederick County" → "Frederick"
    - "Baltimore city" → "Baltimore City" (preserves "City" for independent cities)
    - "Charles City County" → "Charles City" (preserves "City" in county name)
    - "St. Louis city" → "St. Louis City"
    """
    # Handle "X city" (Census format for independent cities) before stripping County
    city_m = _CITY_SUFFIX_RE.search(name)
    if city_m:
        # "Baltimore city" → "Baltimore City", "St. Louis city" → "St. Louis City"
        # But "Charles City County" should become "Charles City" (strip County only)
        stripped = name[: city_m.start()] + " City"
        # If there's also a "County" after "City", strip it
        return _SUFFIX_RE.sub("", stripped).strip()
    return _SUFFIX_RE.sub("", name).strip()


class Enricher:
    """Loads Census lookup tables once; enriches EventItems with county/state/city."""

    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)

        zip_path = data_dir / "zip-county.json"
        city_path = data_dir / "city-county.json"

        try:
            with open(zip_path) as fh:
                self._zip_county: dict[str, dict] = json.load(fh)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Census ZIP lookup not found at {zip_path}. "
                "Run scripts/build-zip-county.sh to generate it."
            ) from None

        try:
            with open(city_path) as fh:
                self._city_county: dict[str, dict] = json.load(fh)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Census city lookup not found at {city_path}. "
                "Run scripts/build-zip-county.sh to generate it."
            ) from None

        self._county_re = self._build_county_re()

    def _build_county_re(self) -> re.Pattern:
        """Build a single regex matching any known county name (longest first)."""
        seen: set[str] = set()
        unique: list[str] = []
        all_counties = [c for counties in COUNTIES.values() for c in counties]
        for county in sorted(all_counties, key=len, reverse=True):
            if county.lower() not in seen:
                seen.add(county.lower())
                unique.append(re.escape(county))
        pattern = r"\b(" + "|".join(unique) + r")\b"
        return re.compile(pattern, re.IGNORECASE)

    def _canonical_county(self, name: str, raw_name: str, state: str) -> str:
        """Return canonical county name from COUNTIES.

        Tries exact match first, then case-insensitive match.
        The raw_name comes from zip-county.json (already normalized to
        counties.json format) or from city-county.json (also normalized).
        Falls back to the stripped name if no match found.
        """
        const = COUNTIES.get(state, [])
        for c in const:
            if c == name:
                return c
        for c in const:
            if c.lower() == name.lower():
                return c
        # Fallback: try raw_name (may be useful for edge cases)
        for c in const:
            if c.lower() == raw_name.lower():
                return c
        return name

    def _canonical_county_full(self, county: str, raw_name: str, state: str) -> str:
        const = COUNTIES.get(state, [])
        if county in const and re.search(
            r"\b(?:County|City|Borough)\b", county, re.IGNORECASE
        ):
            return county
        for c in const:
            if c.lower() == county.lower():
                if re.search(r"\b(?:County|City|Borough)\b", c, re.IGNORECASE):
                    return c
                return c + " County"
        return raw_name

    def enrich(self, event: EventItem) -> EventItem:
        """Fill county/county_full/state/city from the event's address data."""
        addr_full = event.addr_full

        # ── Tier 1: ZIP → county lookup ──────────────────────────────────────
        if event.zip and event.zip in self._zip_county:
            entry = self._zip_county[event.zip]
            raw_county = entry["county"]
            state = entry["state"]
            stripped = _strip_suffix(raw_county)
            event.county = self._canonical_county(stripped, raw_county, state)
            event.county_full = self._canonical_county_full(
                event.county, raw_county, state
            )
            event.state = state

        # ── Tier 2: Scan address/venue/title for known county names ──────────
        if not event.county and addr_full:
            scan = f"{addr_full} {event.venue} {event.name}"
            m = self._county_re.search(scan)
            if m:
                matched = m.group(1)
                candidate_states = ([event.state] if event.state else []) + [
                    s for s in STATE_ORDER if s != event.state
                ]
                for state_code in candidate_states:
                    for c in COUNTIES[state_code]:
                        if c.lower() == matched.lower():
                            event.county = c
                            if re.search(
                                r"\b(?:County|City|Borough)\b",
                                c,
                                re.IGNORECASE,
                            ):
                                event.county_full = c
                            else:
                                event.county_full = c + " County"
                            if not event.state:
                                event.state = state_code
                            break
                    if event.county:
                        break

        # ── Tier 3: City → county lookup ─────────────────────────────────────
        if not event.county:
            city = self._extract_city(addr_full, event.venue)
            if city:
                try_states = ([event.state] if event.state else []) + [
                    s for s in STATE_ORDER if s != event.state
                ]
                city_title = city.strip().title()
                for state_code in try_states:
                    key = f"{state_code}:{city_title}"
                    if key in self._city_county:
                        raw_county = self._city_county[key]["county"]
                        stripped = _strip_suffix(raw_county)
                        event.county = self._canonical_county(
                            stripped, raw_county, state_code
                        )
                        event.county_full = self._canonical_county_full(
                            event.county, raw_county, state_code
                        )
                        event.state = state_code
                        if not event.city:
                            event.city = city
                        break

        # ── City extraction (always attempt) ─────────────────────────────────
        if not event.city and addr_full:
            event.city = self._extract_city(addr_full, event.venue)

        if not event.county:
            logger.debug(
                "County not resolved for %r (zip=%r addr=%r)",
                event.name,
                event.zip,
                addr_full[:60] if addr_full else "",
            )

        return event

    def _extract_city(self, addr_full: str, venue: str) -> str:
        """Return the city from an address string, or '' if not resolvable.

        Takes the last comma-separated segment after stripping state/ZIP,
        then rejects it if it contains digits (indicating a street address).
        """
        if not addr_full:
            return ""
        stripped = _STATE_ZIP_RE.sub("", addr_full).strip()
        stripped = _TRAILING_COMMA_RE.sub("", stripped).strip()
        parts = [p.strip() for p in stripped.split(",") if p.strip()]
        if not parts:
            return ""
        city = parts[-1]
        if re.search(r"\d", city):
            return ""
        return city
