# HISS Future Development Roadmap

> Each gap is tagged with priority (HIGH/MED/LOW) and estimated effort (S/M/L).
> Gaps are grouped by concern area, not implementation order.

---

## 1. Data Quality — Ingest Bugs

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 1.1 | HTML location parsing breaks on venue names with commas | HIGH | S | `ingest/html_handler.py:189-196` — comma-split assumes `venue, city, state` order. A venue like "Hotel, Restaurant & Convention Center, Frederick, MD" produces 4 parts: venue="Hotel", city="Restaurant & Convention Center", state="Frederick" — garbage data. Fix: split on last two commas instead of all commas. |
| 1.2 | 2-part location parsing mislabels city/state | HIGH | S | `ingest/html_handler.py:193-195` — when only 2 comma parts exist (e.g. "Frederick, MD" with no venue), venue gets the city and city gets the state. Fix: add `len(parts) == 2` branch where venue="" and city/state are correctly assigned. |
| 1.3 | Directory ingest only grabs first HTML file | HIGH | S | `ingest/__init__.py:37-40` — `_resolve_path()` only searches `.html`/`.htm` when passed a directory. CSV/JSON files are ignored. Error message misleadingly says "No HTML/CSV/JSON files found". Fix: search all supported extensions, return list so all files are processed. |
| 1.4 | "Na" contact filter is case-sensitive | MED | S | `ingest/html_handler.py:256` — `email_val != "na"` lets "Na" through (capital N). Fix: case-insensitive comparison. |
| 1.5 | No state validation in CSV/JSON handlers | MED | S | CSV and JSON handlers don't validate state against `STATE_ORDER`. Non-target states flow through silently until `run.py` date filter drops them. Fix: add validation in handler or at least a warning. |
| 1.6 | No ZIP format validation in any ingest handler | MED | S | Non-numeric ZIPs, 9-digit ZIPs, and Canadian postal codes pass through. Fix: validate ZIP is exactly 5 digits. |
| 1.7 | JSON handler coerces booleans to garbage venue names | LOW | S | `json_handler.py:77` — `str(location)` on a boolean produces "True" as venue. Fix: only coerce strings. |
| 1.8 | CSV handler only supports UTF-8-sig encoding | MED | S | Windows Excel exports (cp1252) crash with `UnicodeDecodeError`. Fix: try UTF-8-sig, fall back to cp1252/latin1 with warning. |

---

## 2. Data Quality — Dedup Blind Spots

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 2.1 | Equal-priority tiebreaker is order-dependent, not quality-based | MED | M | Three source types at priority 0 (festivalnet, json_ingest, csv_ingest) break ties only on page_score. When page_score also ties, first-seen wins — arbitrary. Fix: add a secondary tiebreaker (e.g. prefer the event with more populated fields). |
| 2.2 | Fuzzy merge chain corruption with 3+ events | MED | M | `dedup.py:194-247` — when A merges with B, then A merges with C, B's `primary_url` is added to A's `sources[]` but C's location data may never backfill A because A already has those fields from B. Fix: after chain merges, re-check field backfills from all losers. |
| 2.3 | No test for Jaccard threshold boundary (0.60) | MED | S | Current tests only verify above/below threshold. The boundary cases (0.599 vs 0.600) are not exercised. Add boundary tests. |
| 2.4 | No test for dedup priority of url_enrich vs serper_events | LOW | S | Both are priority 1. Only page_score breaks ties. Not tested. |

---

## 3. Data Quality — Enrichment Edge Cases

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 3.1 | ZIP+4 format breaks Tier 1 enrichment | MED | S | `enrich.py:126` — looks up `event.zip` in `zip-county.json`. If ZIP is `"21701-1234"`, lookup fails silently. Fix: strip +4 before lookup, or add +4-aware matching. |
| 3.2 | Title-case city names corrupt lookup keys | MED | S | `enrich.py:182` — `city.strip().title()` produces "O'fallon" for "O'FALLON", "Mchenry" for "McHenry". Fix: use proper title-case or match insensitively in the lookup table. |
| 3.3 | County names with apostrophes untested with word boundaries | LOW | S | `\b(Queen Anne's)\b` — the `\b` between `e` and `'` may fail. Add regex tests for apostrophe-bearing county names. |
| 3.4 | Non-HTTPS URLs permanently unenrichable | MED | L | `url_enrich.py:111` — SSRF guard blocks HTTP. Many small event sites still use HTTP. Fix: allow HTTP for enrichment with additional SSRF protections (e.g. connect and check IP first). |
| 3.5 | No per-domain rate limiting in URL enrichment | LOW | S | `url_enrich.py:37` — `_DOMAIN_DELAY_SECONDS` is defined but never used. Multiple events on the same domain can be hit concurrently by ThreadPoolExecutor. Fix: implement per-domain rate limiting. |
| 3.6 | Partial JSON-LD extraction blocks heuristic fallback | MED | M | `url_enrich.py` — if JSON-LD has city+state but no ZIP, enrichment stops at the first successful extractor. The ZIP from heuristic is never tried. Fix: merge extraction results from all methods rather than first-wins. |

---

## 4. Test Coverage Gaps

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 4.1 | No sync batch failure tests | HIGH | M | `sync_from_store` has explicit retry logic for failed batches but no test exercises it. Critical path: batch 2 of 3 fails → only batch 2 events remain unsynced → retry on next run. |
| 4.2 | No Serper HTTP 429 rate-limit tests | HIGH | M | `serper.py` has 30s wait + single retry on 429. Completely untested. |
| 4.3 | No full pipeline integration test | HIGH | L | Individual components tested in isolation. No test for the full chain: ingest → fetch → enrich → dedup → store → sync. |
| 4.4 | No malformed input tests for parse_dates | MED | M | No tests for: None dict keys, numeric/boolean inputs, lists as dates, leap years, multi-year ranges ("Dec 2025 – Jan 2026"). |
| 4.5 | No malformed JSON-in-DB tests for sync | MED | S | `_safe_json_load` handles `JSONDecodeError` but no test supplies bad JSON to the DB row. |
| 4.6 | No store error-injection tests | LOW | M | Disk full, DB locked, concurrent access. Hard to test but worth documenting expected behavior. |
| 4.7 | No serialize/deserialize round-trip test for to_db_row | LOW | S | `to_db_row()` → DB → read back → reconstruct EventItem. Not tested. |
| 4.8 | No Eventbrite-like source replacement tests | LOW | S | The high-priority source tests (`festivalnet_wins_over_serper`) test priority but not field merging. |

---

## 5. Search Result Quality (Serper Refinement)

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 5.1 | Serper queries double-count across years | MED | M | `build_queries_for_state` generates queries for current + next year (946 → 1892). This doubles API usage. Consider: incrementally query next year starting at month 6. |
| 5.2 | No date range parameter in Serper queries | MED | M | Serper queries include year but no date range. Results for past dates are filtered post-fetch. Fix: use Serper's date parameters if supported. |
| 5.3 | No result freshness tracking | LOW | M | Events from previous pipeline runs are never re-fetched. If an event's details change (new venue, cancelled), the pipeline won't update it until a new matching result appears. Fix: re-fetch events with primary_urls closing in on their start date. |
| 5.4 | Organic result quality scoring is coarse | MED | M | `organics_to_events` uses simple keyword matching. Could use title quality heuristics, domain authority scoring, or snippet length as quality signals. |
| 5.5 | No SERP dedup across query variations | LOW | M | Same event can appear in "home show Maryland 2027" and "home improvement expo PA 2027". URL-based dedup catches this but only after fetching both. Fix: de-duplicate queries that are likely to return the same results, or use a shared URL dedup cache during fetch. |

---

## 6. URL Enrichment Quality

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 6.1 | Enrichment success rate unknown in aggregate | MED | S | `enrich_from_urls` logs per-run stats but no aggregate metrics exist. Add: persistent enrichment stats (success rate by extraction method, domain response time). |
| 6.2 | No retry for HTTP 5xx during enrichment | MED | S | `url_enrich.py` retries once on `RequestException` but not on server errors. Add: retry with backoff on 500/502/503. |
| 6.3 | No surrogate enrichment (try alternative domains) | LOW | M | If `primary_url` is a dead domain, no fallback to similar URLs. Eventbright/facebook events especially suffer. Remove this gap — not relevant post-Eventbrite removal. |
| 6.4 | Sidecar (Playwright) never used in production | LOW | L | The sidecar infrastructure exists (`sidecar/server.py`) but requires separate deployment. The static-only `url_enrich.py` gets ~60% success. JS-heavy SPAs remain unfetchable. |
| 6.5 | No robots.txt or rate-limit compliance | LOW | M | `url_enrich.py` makes concurrent requests without respecting target-site rate limits or robots.txt. Low risk for a weekly batch but technically non-compliant. |

---

## 7. Frontend Data Quality

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 7.1 | Missing csv_ingest/json_ingest from VALID_SOURCES whitelist | MED | S | `index.html:1433` — the `VALID_SOURCES` Set used for source pills omits `csv_ingest` and `json_ingest`. CSV/JSON-ingested events display "CSV"/"JSON" in the SOURCE table column but have no source pill. Fix: add to whitelist, `labels`, `cssClassMap`, and CSS. |
| 7.2 | CSV export crashes on null sources entries | MED | S | `index.html:1535` — `e.altUrls.map(u => u.url)` without null guard. If `sources[]` contains a null entry, throws `TypeError`. Fix: `u?.url || ''`. |
| 7.3 | Orphaned .facebook CSS class | LOW | S | `index.html:428` — `.source-pill.facebook` defined but no code path produces `facebook` sourceType (pipeline never tags events this way). Remove or document as future-proofing. |
| 7.4 | Two separate source-type label maps | MED | S | `labels`/`cssClassMap` in `runSearch()` and `srcLabelShort()` are separate objects that both map source types to display labels. DRY violation — adding a source type requires updating 3 places. Fix: consolidate into a single `SOURCE_META` object. |
| 7.5 | CSV export unquoted fields | LOW | S | City, State, Type, Coverage, Source, URL fields are not quoted in CSV. If any contain a comma, columns misalign. Fix: quote all fields. |
| 7.6 | Date filter silently drops events without startDate | LOW | S | `applyFilters: dateRange` excludes events with empty startDate with no user indication. Add: display count of hidden date-less events. |
| 7.7 | Coverage modal buttons use onclick with string interpolation | LOW | S | `onclick="modalSelectAll('${state}')"` — fragile to special characters in state codes. Fine with current `STATE_ORDER` but breakable. Fix: use data attributes and event delegation. |

---

## 8. Monitoring & Observability

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 8.1 | No pipeline run health metrics | HIGH | M | No tracking of: events per run, dedup ratio, enrichment success rate trends, sync latency, store size over time. Add: structured logging or Prometheus metrics. |
| 8.2 | No Meilisearch sync drift detection | HIGH | M | No script that compares SQLite synced count to Meilisearch doc count. Ghost documents accumulate if deletion API calls fail. Add: `scripts/check-sync-drift.py`. |
| 8.3 | No alerted pipeline failure | MED | M | Pipeline failures are logged but no alerting mechanism exists. If the scheduler crashes at 3am Sunday, no one notices until Monday. Fix: healthcheck endpoint that reports last successful run time. |
| 8.4 | No FestialNet data freshness tracking | LOW | S | Manual ingest has no tracking of when FestivalNet data was last imported. Stale FestivalNet events may persist indefinitely (they have page_score=3 and win dedup). Add: ingest timestamp metadata. |

---

## 9. Developer Infrastructure

| # | Gap | Priority | Effort | Details |
|---|---|---|---|---|
| 9.1 | No Hypothesis property-based tests | MED | M | Current tests use specific inputs. Hypothesis would find edge cases automatically: `parse_dates` never crashes on any input type, `dedup` is idempotent, `store` round-trip preserves data. Add `hypothesis` to `requirements-dev.txt`. |
| 9.2 | No GitHub Actions quality gate on PR | MED | M | Only image publish workflows exist. No PR workflow that runs tests, lint, and quality checks before merge. Add: `.github/workflows/quality-gate.yml`. |
| 9.3 | No data integrity check tooling | MED | M | No script that validates: all ZIPs in lookup tables, all counties in COUNTIES have entries in both lookup tables, no orphaned source_queries, consistent county_full suffixes. Add: `scripts/validate-data.py`. |
| 9.4 | Test count in AGENTS.md docs is stale | LOW | S | AGENTS.md references specific test counts (241, 259) that drift with every test change. Replace with reference to `pytest --collect-only -q` output. |

---

## 10. Server-Side Quality: Post-Store Validation

> These would be checks in a new `pipeline/quality.py` module, run after store upsert
> but before Meilisearch sync. Failing checks block sync in CI, warn in production.

| # | Check | Severity |
|---|---|---|
| 10.1 | `REQUIRED_FIELDS_PRESENT` — events with empty name, start_date, or state | BLOCK |
| 10.2 | `ZIP_FORMAT_VALID` — ZIPs not matching 5-digit numeric pattern | BLOCK |
| 10.3 | `ZIP_IN_LOOKUP_TABLE` — ZIPs not in zip-county.json | WARN |
| 10.4 | `STATE_IN_TARGET_STATES` — state code not in STATE_ORDER | BLOCK |
| 10.5 | `COUNTY_IN_CANONICAL_LIST` — county name not in COUNTIES[state] | WARN |
| 10.6 | `EVENT_TYPE_VALID` — event_type not in EVENT_TYPES | WARN |
| 10.7 | `DATE_RANGE_VALID` — start_date > end_date | BLOCK |
| 10.8 | `DATE_IN_REASONABLE_WINDOW` — dates before 2020 or after 2030 | WARN |
| 10.9 | `URL_SCHEME_VALID` — primary_url doesn't start with http:// or https:// | WARN |
| 10.10 | `PAGE_SCORE_RANGE` — page_score outside 0-3 | BLOCK |
| 10.11 | `COUNTY_FULL_CONSISTENT` — county_full doesn't end with known suffix or match city entity | WARN |
| 10.12 | `ZIP_CONSISTENT_WITH_STATE` — ZIP resolves to different state than event.state | WARN |
| 10.13 | `COUNTY_CONSISTENT_WITH_STATE` — county name exists in COUNTIES but for wrong state | WARN |
| 10.14 | `SOURCE_TYPE_VALID` — source_type not in known types | BLOCK |
| 10.15 | `SOURCES_JSON_PARSEABLE` — sources or source_queries JSON is malformed | BLOCK |
| 10.16 | `POST_DEDUP_NAME_SIMILARITY` — events with same county+year and Jaccard ≥0.85 but different event_ids (probable missed merge) | WARN |
| 10.17 | `POST_DEDUP_URL_COLLISION` — events with same primary_url but different event_ids | WARN |
| 10.18 | `DUPLICATE_SOURCES` — same URL appears in multiple events' sources[] lists | WARN |
| 10.19 | `POPULATION_STATS` — counts per state, source, event type (always informational) | INFO |

---

## Implementation Priority Order (Recommended)

```
Phase 1 — Critical bugs (1 day)
  1.1  HTML comma-in-venue fix
  1.2  2-part location fix
  1.3  Directory ingest fix
  7.2  CSV export null guard
  10.1  REQUIRED_FIELDS_PRESENT quality check
  10.4  STATE_IN_TARGET_STATES quality check

Phase 2 — Data integrity tooling (2 days)
  8.2  Sync drift detection
  10.x  Full quality.py module (all 19 checks)
  9.3  validate-data.py script

Phase 3 — Enrichment quality (3 days)
  3.1  ZIP+4 fix
  3.2  Title-case city fix
  3.6  Multi-method extraction merging
  6.1  Enrichment metrics
  6.2  5xx retry

Phase 4 — Serper refinement (2 days)
  5.2  Date range parameters
  5.4  Organic quality scoring
  5.1  Query optimization

Phase 5 — Test coverage (3 days)
  4.1  Sync batch failure tests
  4.2  Serper 429 tests
  4.3  Integration test
  4.4  Malformed input tests
  9.1  Hypothesis tests

Phase 6 — Frontend fixes (1 day)
  7.1  csv_ingest/json_ingest source pills
  7.4  Consolidate source label maps
  7.5  Quote all CSV fields
  7.3  Remove orphaned CSS

Phase 7 — Monitoring (2 days)
  8.1  Pipeline health metrics
  8.3  Alerted failures
  9.2  CI quality gate
```
