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
_PUNC_RE = re.compile(
    r"[."
    r"'"     # U+0027 ASCII apostrophe
    r"’"  # U+2019 right single quotation mark (curly close)
    r"‘"  # U+2018 left single quotation mark (curly open)
    r"ʼ"  # U+02BC modifier letter apostrophe
    r"]"
)
# Matches county/city/borough/parish suffix — used to decide whether to add
# a "county" suffix when building _county_norm lookup keys.
_SUFFIX_CHECK_RE = re.compile(r"\b(?:county|city|borough|parish)\b", re.IGNORECASE)


def _punc_normalize(s: str) -> str:
    """Strip periods and apostrophe variants for fuzzy county name matching."""
    return _PUNC_RE.sub("", s)


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

        # Build per-state map of normalized county name → canonical county name.
        # Used by tier 2 to convert the punctuation-stripped regex match back to
        # the canonical form (e.g. "st marys county" → "St. Mary's County").
        # Also maps the "+ county" variant for bare names (COUNTIES stores "St. Mary's"
        # not "St. Mary's County") so external data like "St Marys County" resolves.
        self._county_norm: dict[str, dict[str, str]] = {}
        for state, counties in COUNTIES.items():
            state_map: dict[str, str] = {}
            for c in counties:
                norm = _punc_normalize(c).lower()
                if norm not in state_map:
                    state_map[norm] = c
                # For bare names like "St. Mary's", also map "st marys county" so
                # externally-supplied values with suffix ("St Marys County") resolve.
                if not _SUFFIX_CHECK_RE.search(norm):
                    norm_county = norm + " county"
                    if norm_county not in state_map:
                        state_map[norm_county] = c
            self._county_norm[state] = state_map

        self._county_re = self._build_county_re()

    def _build_county_re(self) -> re.Pattern:
        """Build a regex matching any known county name, punctuation-normalized.

        Patterns are built from normalized names (periods and apostrophes stripped)
        so the regex is applied against normalized scan text. Deduplication is also
        done on the normalized form to avoid conflicting alternates.
        """
        seen: set[str] = set()
        unique: list[str] = []
        all_counties = [c for counties in COUNTIES.values() for c in counties]
        for county in sorted(all_counties, key=len, reverse=True):
            norm = _punc_normalize(county)
            if not norm:
                logger.warning("County %r normalizes to empty string — skipping", county)
                continue
            if norm.lower() not in seen:
                seen.add(norm.lower())
                unique.append(re.escape(norm))
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
        # ZIP codes uniquely identify states. If the ZIP resolves to a different
        # state than event.state (which came from the Serper query string), the
        # ZIP-based state is authoritative — correct it.
        if event.zip and event.zip in self._zip_county:
            entry = self._zip_county[event.zip]
            raw_county = entry["county"]
            state = entry["state"]
            if event.state and event.state != state:
                logger.debug(
                    "State correction via ZIP: %r state %s → %s (zip=%s)",
                    event.name[:50],
                    event.state,
                    state,
                    event.zip,
                )
            stripped = _strip_suffix(raw_county)
            event.county = self._canonical_county(stripped, raw_county, state)
            event.county_full = self._canonical_county_full(
                event.county, raw_county, state
            )
            event.state = state

        # ── Tier 2: Scan address/venue/title for known county names ──────────
        # Scan text is punctuation-normalized (periods/apostrophes stripped) so
        # "St Marys County Fair" matches the canonical "St. Mary's County".
        if not event.county and addr_full:
            scan = _punc_normalize(f"{addr_full} {event.venue or ''} {event.name or ''}")
            m = self._county_re.search(scan)
            if m:
                matched_norm = m.group(1).lower()
                if event.state:
                    candidate_states = [event.state]
                else:
                    candidate_states = list(STATE_ORDER)
                for state_code in candidate_states:
                    canonical = self._county_norm.get(state_code, {}).get(matched_norm)
                    if canonical:
                        event.county = canonical
                        if re.search(
                            r"\b(?:County|City|Borough)\b",
                            canonical,
                            re.IGNORECASE,
                        ):
                            event.county_full = canonical
                        else:
                            event.county_full = canonical + " County"
                        if not event.state:
                            event.state = state_code
                        break

        # ── Tier 3: City → county lookup ─────────────────────────────────────
        if not event.county:
            city = self._extract_city(addr_full, event.venue)
            if city:
                if event.state:
                    try_states = [event.state]
                else:
                    try_states = list(STATE_ORDER)
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

        # ── Post-enrichment county normalization ──────────────────────────────
        # URL enrichment or Serper organic data can set county to an all-caps
        # variant ("ALLEGANY") or punctuation-stripped variant ("St Marys County").
        # Normalize against the canonical list using _county_norm for consistency.
        if event.county and event.state:
            norm = _punc_normalize(event.county).lower()
            canonical = self._county_norm.get(event.state, {}).get(norm)
            if canonical and canonical != event.county:
                event.county = canonical
                # Always recompute county_full when county is corrected so the two
                # fields never diverge (e.g. county="St. Mary's" but county_full
                # still holds the uncorrected "St Marys County" from external data).
                if re.search(r"\b(?:County|City|Borough)\b", canonical, re.IGNORECASE):
                    event.county_full = canonical
                else:
                    event.county_full = canonical + " County"

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
