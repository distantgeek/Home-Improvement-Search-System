"""
Deduplication logic (ported from index.html dedupeKey / fuzzyMergeResults).

Pass 1 (exact_dedup):  dedup key = normalized_name|year|locality
Pass 2 (fuzzy_merge):  Jaccard similarity ≥ 0.60 within year|county buckets

Key fix over the JS original: fuzzy buckets use year|county, not
startDate|zip|city|state — events with slightly different parsed dates or
missing ZIPs now land in the same bucket and get compared.
"""

from __future__ import annotations

import re

from .models import EventItem, make_event_id

_EVENT_CORE_RE = re.compile(r"\b(fair|show|expo|festival|exhibit|convention)\b")
_NOISE_RE = re.compile(
    r"\b(maryland|virginia|pennsylvania|washington\s*dc|new\s*jersey|delaware"
    r"|md|va|pa|dc|nj|de"
    r"|the|annual|official|visit|welcome\s*to|home\s*of|guide|info"
    r"|details?|tickets?|schedule|dates?)\b",
    re.IGNORECASE,
)
_VENUE_NOISE_RE = re.compile(
    r"\b(fairgrounds|convention\s*center|expo\s*center|event\s*center"
    r"|civic\s*center|grounds)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b20\d\d\b")
_NON_WORD_RE = re.compile(r"[^\w\s]")
_MULTI_SPACE_RE = re.compile(r"\s+")

# Lower number = higher priority
_SOURCE_PRIORITY: dict[str, int] = {
    "eventbrite": 0,
    "serper_events": 1,
    "serper_organic": 2,
}


def _priority(source_type: str) -> int:
    return _SOURCE_PRIORITY.get(source_type, 99)


def dedup_key(event: EventItem) -> str:
    """Exact-match dedup key: normalized_name|year|locality."""
    raw = event.name.lower()

    # Smart hyphen: keep the side that contains event keywords
    parts = raw.split(" - ")
    if len(parts) >= 2:
        before = parts[0]
        after = " - ".join(parts[1:])
        b_has = bool(_EVENT_CORE_RE.search(before))
        a_has = bool(_EVENT_CORE_RE.search(after))
        if b_has and not a_has:
            raw = before
        elif a_has and not b_has:
            raw = after

    raw = re.sub(r"\s*:\s*.+$", "", raw)  # "Event: Sub-page"
    raw = re.sub(r"\s*[|–]\s*.+$", "", raw)  # "Event | Site"
    raw = _YEAR_RE.sub("", raw)
    raw = _NON_WORD_RE.sub("", raw)
    raw = _MULTI_SPACE_RE.sub(" ", raw).strip()

    year = event.start_date[:4] if event.start_date else ""
    locality = event.zip or event.state or ""
    return f"{raw}|{year}|{locality}"


def normalize_for_dedup(name: str) -> str:
    """Strip noise words and venue fragments for fuzzy token comparison."""
    s = name.lower()
    s = _NOISE_RE.sub("", s)
    s = _YEAR_RE.sub("", s)
    s = _VENUE_NOISE_RE.sub("", s)
    s = _NON_WORD_RE.sub("", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def jaccard_similarity(a: str, b: str) -> float:
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def exact_dedup(events: list[EventItem]) -> list[EventItem]:
    """Pass 1: merge on exact dedup_key. Returns deduplicated list."""
    seen: dict[str, EventItem] = {}

    for event in events:
        key = dedup_key(event)
        event.dedup_key = key
        event.event_id = make_event_id(key)

        if key not in seen:
            seen[key] = event
            continue

        existing = seen[key]
        new_p = _priority(event.source_type)
        ex_p = _priority(existing.source_type)
        upgrade = new_p < ex_p or (
            new_p == ex_p and event.page_score > existing.page_score
        )

        if upgrade:
            event.source_queries = list(
                dict.fromkeys(existing.source_queries + event.source_queries)
            )
            merged = list(existing.sources)
            for s in event.sources:
                if s.get("url") not in {x.get("url") for x in merged}:
                    merged.append(s)
            event.sources = merged
            seen[key] = event
        else:
            # Merge missing fields from the lower-priority duplicate
            if event.source_type != "serper_organic":
                if not existing.zip and event.zip:
                    existing.zip = event.zip
                if not existing.county and event.county:
                    existing.county = event.county
                    existing.county_full = event.county_full
                    existing.state = event.state
                if not existing.city and event.city:
                    existing.city = event.city
                if not existing.venue and event.venue:
                    existing.venue = event.venue
            if not existing.attendance and event.attendance:
                existing.attendance = event.attendance
            if not existing.contact and event.contact:
                existing.contact = event.contact
            for q in event.source_queries:
                if q not in existing.source_queries:
                    existing.source_queries.append(q)

    return list(seen.values())


def fuzzy_merge_results(events: list[EventItem]) -> list[EventItem]:
    """Pass 2: Jaccard-based fuzzy merge within (year|county) buckets.

    Uses year|county as the bucket key — not startDate|zip — so the same
    event with slightly different parsed dates or missing ZIPs still lands
    in the same bucket and gets compared.
    """
    buckets: dict[str, list[int]] = {}
    for i, event in enumerate(events):
        year = event.start_date[:4] if event.start_date else ""
        county = event.county or event.state or ""
        if not year and not county:
            # No temporal or geographic signal — skip from fuzzy comparison
            # to prevent spurious cross-state merges of unresolved organics
            continue
        key = f"{year}|{county}"
        buckets.setdefault(key, []).append(i)

    merged: set[int] = set()

    for indices in buckets.values():
        if len(indices) < 2:
            continue
        for a in range(len(indices)):
            i = indices[a]
            if i in merged:
                continue
            norm_a = normalize_for_dedup(events[i].name)
            for b in range(a + 1, len(indices)):
                j = indices[b]
                if j in merged:
                    continue
                norm_b = normalize_for_dedup(events[j].name)
                if jaccard_similarity(norm_a, norm_b) < 0.6:
                    continue

                p_i = _priority(events[i].source_type)
                p_j = _priority(events[j].source_type)
                if p_i < p_j or (
                    p_i == p_j and events[i].page_score >= events[j].page_score
                ):
                    winner, loser = i, j
                else:
                    winner, loser = j, i

                # Accumulate alternate URL from loser into winner
                if events[loser].primary_url:
                    events[winner].sources.append(
                        {
                            "url": events[loser].primary_url,
                            "sourceType": events[loser].source_type,
                        }
                    )
                for q in events[loser].source_queries:
                    if q not in events[winner].source_queries:
                        events[winner].source_queries.append(q)
                merged.add(loser)

    return [e for i, e in enumerate(events) if i not in merged]
