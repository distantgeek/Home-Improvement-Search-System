# HISS — Home Improvement Show Search
## Agent Context Document

> This file is the authoritative project brief for all AI coding assistants (Claude Code,
> OpenCode, and others). Read it in full before touching any code. It replaces CLAUDE.md.

---

## 1. Project Identity

**What HISS is:** An event discovery tool for a home improvement company that exhibits
at trade shows, home expos, county fairs, state fairs, and similar events. The company
offers gutter protection, roofing, awnings, and related services across VA, MD, PA, DC,
NJ, and DE.

**The problem it solves:** The event coordinator was manually printing lists from
FestivalNet.com — a craft/art-vendor platform with predatory per-event pricing — and
hand-pruning results by county. That workflow is wrong for the use case and not scalable.

**The solution (current architecture):** A background Python pipeline pre-fetches events
from Serper.dev (Google Events), normalizes and deduplicates them, stores them in SQLite,
and indexes them in Meilisearch. Events with Eventbrite URLs found via Serper are
additionally enriched with structured address data from the Eventbrite Event Retrieval
API (when the API key has the required scope — see Section 8). A static HTML frontend
(currently still calling Serper directly — Phase 1 will change this) lets the coordinator
filter by served counties and export results to CSV.

**End user:** A non-technical event coordinator. The frontend must work by opening a
browser. No terminal, no installs, no configuration files to edit.

**Repository:** `git@github.com:distantgeek/home-improvement-search-system.git`
**GitHub handle:** `distantgeek`

---

## 2. Architecture

### Service table

| Service | Container name | Image | Port | Role |
|---|---|---|---|---|
| Frontend | `hiss` | `ghcr.io/distantgeek/home-improvement-search-system:latest` | 8888 | Static httpd:alpine serving `index.html` |
| Search index | `hiss-meilisearch` | `getmeili/meilisearch:v1.13` | 7700 (host-exposed) | Typo-tolerant REST search; browser queries directly |
| Data pipeline | `hiss-pipeline` | `ghcr.io/distantgeek/home-improvement-search-system/pipeline:latest` | — | Long-lived Python process; APScheduler runs weekly |
| Debug UI | `hiss-datasette` | `datasetteproject/datasette:latest` | 8001 (internal only) | Read-only SQLite browser; no proxy network |

### Docker networks

The repo's `docker-compose.yml` places `hiss` on an external `proxy` network (NPM
Docker network) for environments where NPM and the stack share a Docker overlay.
The **TrueNAS deployment** (`compose.yaml` on the host) uses `ports: "8888:80"` instead,
because NPM routes `hiss.distantgeek.net → 192.168.2.148:8888` by host IP — the proxy
network is not used there.

- `internal` (bridge, this stack) — `hiss-meilisearch`, `hiss-pipeline`, `hiss-datasette`

`hiss-meilisearch` port 7700 is exposed directly on the TrueNAS host so the browser can
query Meilisearch without going through NPM. `hiss-datasette` is intentionally not on
any external network (no built-in auth; raw SQL exposure risk).

### Data flow (pipeline run)

```
Eventbrite Discovery API (Tier 1, optional — returns 404 on free tier)
         │
         ├──→ normalize_event() / parse_dates() / infer_event_type()
         │
Serper.dev Google Events (Tier 2, required)
         │
         ├──→ organics_to_events() for non-carousel results
         │
         └──→ normalize_event()
                    │
                    ▼
              eb_enrich.enrich_from_urls()  ← Eventbrite URL enrichment:
                    │   events whose primary_url/sources point to Eventbrite
                    │   get structured venue/city/state/ZIP from /v3/events/{id}/
                    │   (requires Eventbrite key with retrieval scope; skipped on 401/403/404)
                    ▼
              enrich()  ← three-tier county/ZIP resolution
                    │
                    ▼
              exact_dedup()   ← pass 1: name|year|locality key
                    │
                    ▼
              fuzzy_merge_results()  ← pass 2: Jaccard ≥ 0.60 in year|county buckets
                    │
                    ▼
              store.upsert_events()  ← SQLite (hiss.db), WAL mode
              store.purge_expired()  ← drop events with end_date < today-30d
                    │
                    ▼
              sync.sync_from_store() ← push synced=0 rows to Meilisearch in batches of 100
                                       mark synced=1 on success; failed batches retry next run
```

The pipeline runs once immediately on container start, then on the APScheduler cron
(default: `0 3 * * 0`, weekly Sunday 3am).

---

## 3. Repository Layout

```
home-improvement-search-system/
├── .github/
│   └── workflows/
│       ├── docker-publish.yml       # Builds frontend image on push to main
│       └── pipeline-publish.yml     # Builds pipeline image when pipeline/**,
│                                    #   data/**, or Dockerfile.pipeline changes
├── data/
│   ├── zip-county.json              # ZIP → {state, county} (~3,940 entries, VA/MD/PA/DC/NJ/DE)
│   └── city-county.json             # "STATE:city" → {county} (~3,822 entries)
├── docs/
│   ├── architecture.md              # Detailed architecture doc (superseded by this file)
│   └── county-coverage.md           # Served-county localStorage schema and UI notes
├── scripts/
│   └── build-zip-county.sh          # Regenerates zip-county.json + city-county.json
│                                    #   from U.S. Census ZCTA-to-County/Place files
├── pipeline/
│   ├── __init__.py
│   ├── constants.py                 # COUNTIES dict, STATE_ORDER, STATE_NAMES, EVENT_TYPES
│   ├── models.py                    # EventItem dataclass + make_event_id()
│   ├── normalize.py                 # normalize_event, parse_dates, infer_event_type,
│   │                                #   organics_to_events
│   ├── enrich.py                    # Enricher class — three-tier county/ZIP resolution
│   ├── dedup.py                     # exact_dedup, fuzzy_merge_results, jaccard_similarity
│   ├── store.py                     # Store class — SQLite UPSERT, purge, mark_synced
│   ├── sync.py                      # MeilisearchSync — configure_index, sync_from_store
│   ├── run.py                       # Entry point — orchestrate, APScheduler, --dry-run
│   ├── requirements.txt             # requests, beautifulsoup4, rapidfuzz, meilisearch,
│   │                                #   python-dateutil, APScheduler
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── serper.py                # Tier 2: Serper.dev + organics fallback
│   │   ├── eventbrite.py            # Tier 1: Eventbrite Discovery API (optional, enterprise-only)
│   │   └── eventbrite_enrich.py     # URL enrichment: /v3/events/{id}/ for Eventbrite-linked events
│   ├── spiders/
│   │   └── .gitkeep                 # Phase 2 placeholder — Scrapy curated crawlers
│   └── tests/
│       ├── conftest.py              # tmp_db fixture, sample fixtures
│       ├── test_normalize.py
│       ├── test_enrich.py
│       ├── test_dedup.py
│       ├── test_store.py
│       ├── test_sync.py
│       ├── test_serper.py
│       ├── test_eventbrite.py
│       ├── test_eventbrite_enrich.py
│       └── fixtures/
│           ├── serper_events_response.json
│           ├── serper_organic_response.json
│           └── eventbrite_response.json
├── Dockerfile                       # Frontend: httpd:alpine serving index.html
├── Dockerfile.pipeline              # Pipeline: python:3.12-slim, runs as UID 1000
├── docker-compose.yml               # All four services + volumes + networks
├── .env.example                     # Template for required env vars (copy to .env)
├── index.html                       # Complete frontend app (currently calls Serper directly)
├── AGENTS.md                        # This file — primary agent context document
├── README.md                        # Human-readable setup and usage
└── LICENSE
```

---

## 4. Current State

### Phase 0 — complete and deployed

The full pipeline is implemented, deployed on TrueNAS, and running.
**126/126 tests pass** (`python3 -m pytest pipeline/tests/`).

Completed work:
- `pipeline/` package — all modules implemented, including `eventbrite_enrich.py`
- `Dockerfile.pipeline` — python:3.12-slim, non-root `pipeline` user (UID 1000)
- `docker-compose.yml` — four services with internal network, log rotation, healthcheck
- `.env.example` — template with all required variables
- `.github/workflows/pipeline-publish.yml` — CI auto-build on relevant path changes
- `data/zip-county.json` + `data/city-county.json` — Census-derived lookup tables
- Deployed and running on TrueNAS at `192.168.2.148` — 980+ events indexed in Meilisearch

The existing frontend (`index.html`) continues to call Serper.dev directly — Phase 0
is purely additive. The coordinator's workflow is unchanged while the pipeline runs
silently in the background.

### Phase 1 — not started

Modify `index.html` to query Meilisearch instead of calling Serper.dev directly.
See section 10 for the complete spec.

### Phase 2 — not started

Add Scrapy spiders (`pipeline/spiders/`) for curated sources: state fair official sites,
home show association pages, regional aggregators. Output feeds the same normalize →
enrich → dedup → store → sync chain.

---

## 5. Deployment on TrueNAS

### Target host

- **IP:** `192.168.2.148`
- **SSH:** `ssh truenas` (alias in `~/.ssh/config`; user `assistant`, key `~/.ssh/id_ed25519_truenas`)
- **Stack path:** `/mnt/kevbot-store/stacks/home-improvement-show-search/` (requires `sudo` to read/write)
- **Docker:** `sudo docker ...` — `assistant` is not in the docker group

### Stack is already deployed

The stack is live. To manage it:

```bash
# Check status
ssh truenas "sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml ps"

# View pipeline logs
ssh truenas "sudo docker logs hiss-pipeline --tail 40"

# Pull new image and restart after a push to main
ssh truenas "sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml pull hiss-pipeline && sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml up -d hiss-pipeline"
```

### First deployment (reference — already done)

1. Copy `compose.yaml` and `.env` to `/mnt/kevbot-store/stacks/home-improvement-show-search/` on the host.
   Note: The TrueNAS `compose.yaml` uses `ports: "8888:80"` on the `hiss` service (not the proxy
   network) because NPM routes `hiss.distantgeek.net → 192.168.2.148:8888` by host IP.
2. Create `.env` from `.env.example`. Set `MEILI_MASTER_KEY`, `SERPER_API_KEY`, `EVENTBRITE_API_KEY`.
3. Set `.env` permissions: `chmod 600 .env`
4. Fix volume permissions so the pipeline container (UID 1000) can write to `/data`:
   ```bash
   sudo docker run --rm -v home-improvement-show-search_pipeline_data:/data busybox chown -R 1000:1000 /data
   ```
5. Start: `sudo docker compose -f compose.yaml up -d`
5. After Meilisearch starts, create the search-only key:

```bash
curl -X POST http://192.168.2.148:7700/keys \
  -H "Authorization: Bearer $MEILI_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"HISS Browser Search Key","actions":["search"],"indexes":["events"],"expiresAt":null}'
```

Copy the returned `"key"` value into `MEILI_SEARCH_KEY` in `.env`, then redeploy
`hiss-pipeline` so it has the key available for Phase 1 frontend config.

### Updating images

After a push to `main` that triggers GitHub Actions:

1. In Dockge, pull the updated image for the relevant service.
2. Recreate the container (Dockge "Update" button or `docker compose pull && docker compose up -d`).

The pipeline image auto-builds when `pipeline/**`, `data/**`, or `Dockerfile.pipeline`
changes. The frontend image auto-builds on any push to `main`.

### Datasette access (debug only)

Datasette is internal-only. SSH tunnel to browse `hiss.db`:

```bash
ssh -L 8001:hiss-datasette:8001 assistant@192.168.2.148
# then open http://localhost:8001/ in a browser
```

### Verify pipeline ran

```bash
curl http://192.168.2.148:7700/indexes/events/stats
# should show numberOfDocuments > 0 after the first run completes
```

---

## 6. Development Workflow

### Running tests

```bash
cd /path/to/home-improvement-search-system
python3 -m pytest pipeline/tests/
# Expected: 126 passed
```

Tests use the `responses` library and `unittest.mock` to intercept HTTP calls — no live
API calls. The `tmp_db` fixture in `conftest.py` provides a file-based SQLite database
(not `:memory:`, for WAL compatibility). Note: `@responses_lib.activate` must be applied
to individual test methods, not classes — the class decorator silently drops tests in
Python 3.14.

### Dry-run mode

Test the full pipeline chain locally without making API calls or writing to SQLite/Meilisearch:

```bash
cd pipeline
DRY_RUN=true SERPER_API_KEY=dummy MEILI_MASTER_KEY=dummy \
  python3 -m pipeline.run --dry-run
```

Logs sample output (up to 5 events) and exits without writing anything.

### Run once (non-scheduled)

```bash
SERPER_API_KEY=... MEILI_MASTER_KEY=... MEILI_URL=http://localhost:7700 \
  python3 -m pipeline.run --once
```

### Regenerate Census lookup tables

```bash
./scripts/build-zip-county.sh
# Produces data/zip-county.json and data/city-county.json
# Requires: bash, curl, awk, python3
```

### CI workflow summary

`pipeline-publish.yml` triggers on push to `main` when `pipeline/**`, `data/**`, or
`Dockerfile.pipeline` changes (also on `workflow_dispatch`). It:
1. Logs in to GHCR with `GITHUB_TOKEN`
2. Extracts metadata (`latest` tag + `sha-<short>` tag)
3. Builds `Dockerfile.pipeline` with context `.`
4. Pushes to `ghcr.io/distantgeek/home-improvement-search-system/pipeline`

`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` is set to avoid Node.js 20 deprecation
warnings in GitHub Actions.

---

## 7. Environment Variables

All variables are read by `pipeline/run.py` via `_load_config()` at startup.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SERPER_API_KEY` | Yes (non-dry-run) | — | Serper.dev API key; `POST google.serper.dev/search` |
| `MEILI_MASTER_KEY` | Yes (non-dry-run) | — | Meilisearch master key; placeholder value rejected at startup |
| `EVENTBRITE_API_KEY` | No | — | Eventbrite Discovery API key; Tier 1 skipped if absent |
| `MEILI_URL` | No | `http://hiss-meilisearch:7700` | Meilisearch base URL; must start with `http://` or `https://` (SSRF guard) |
| `MEILI_SEARCH_KEY` | No | — | Search-only Meilisearch key; provided to frontend in Phase 1 |
| `DB_PATH` | No | `/data/hiss.db` | SQLite database path inside the container |
| `DATA_DIR` | No | `../data` (relative to `pipeline/`) | Directory containing `zip-county.json` and `city-county.json` |
| `PIPELINE_SCHEDULE` | No | `0 3 * * 0` | 5-part cron expression for APScheduler |
| `DRY_RUN` | No | `false` | Set to `true` to skip all API calls and writes; useful for testing |
| `NPM_NETWORK_NAME` | Compose only | — | External Docker network name for NPM; used in `docker-compose.yml` |

---

## 8. Pipeline Module Guide

### `pipeline/run.py`

Entry point. `_load_config()` reads env vars and validates `MEILI_URL` scheme and
`MEILI_MASTER_KEY` placeholder at startup — exits with an error if either fails. The
`run_pipeline()` function orchestrates one full pass: fetch (Eventbrite, then Serper),
enrich, date-filter to current year, exact dedup, fuzzy dedup, upsert to SQLite, purge
expired, sync to Meilisearch. In long-lived mode, APScheduler wraps `run_pipeline()`
and runs it once immediately on startup, then on the configured cron. `--dry-run` and
`--once` flags bypass the scheduler.

### `pipeline/fetchers/serper.py`

Tier 2 catch-all. `build_all_queries()` generates search strings for all six states
and all eight event types from `constants.COUNTIES`/`EVENT_TYPES` — state-level queries
(e.g. `"home show Maryland 2026"`) plus per-county queries for county fairs. `fetch_all()`
sends each query to `https://google.serper.dev/search` with a 400ms inter-query delay;
on HTTP 429 it waits 30 seconds and retries once before logging and continuing. Results
from `eventsResults[]` are tagged `serper_events`; when that field is absent, `organic[]`
results are passed through `organics_to_events()` and tagged `serper_organic`.

### `pipeline/fetchers/eventbrite.py`

Tier 1 structured source. Uses the Eventbrite Discovery API (`/v3/events/search/`) with
lat/lng centroid + 100mi radius for each target state, paginating until `has_more_items`
is false. Returns structured venue, city, ZIP, and date data directly in the API response
(no address parsing needed). On HTTP 401/403, logs a warning and returns an empty list
without aborting — the Discovery API requires enterprise access and is treated as
optional (currently returns 404 on the free tier; Tier 2 runs regardless). All Eventbrite
events get `page_score=2` (highest priority in dedup).

### `pipeline/fetchers/eventbrite_enrich.py`

Post-fetch URL enrichment. Runs after all fetchers complete but **before** `enrich()` so
that ZIP/venue data from Eventbrite flows into the county resolution pipeline. Scans each
event's `primary_url` and `sources[]` for valid Eventbrite URLs, validates the URL before
calling the API, then validates the response before applying changes.

**Pre-API URL validation** (`extract_eventbrite_id`): rejects non-`https` schemes,
non-`eventbrite.com`/`www.eventbrite.com` hosts (prevents lookalike injection), paths
that don't match `/e/<slug>-<id>`, and IDs outside 5–20 digits.

**Response validation** (`_validate_response`): rejects ID mismatches (response ID must
equal requested ID), cancelled events, and responses with no name-token overlap (generic
names with zero tokens on both sides are accepted — ID match is sufficient in that case).

**Field update** (`_apply_enrichment`): only overwrites non-empty values so a partial
Eventbrite response can't blank fields already populated from Serper. Rebuilds `addr_full`
so `Enricher.enrich()` has the best possible input for the three-tier county resolution.

Runs up to 5 concurrent requests (ThreadPoolExecutor). Each worker creates its own
`requests.Session` for thread safety. Deduplicates by Eventbrite event ID so the same
event is never fetched twice even if it appears in multiple Serper results.

**Current limitation:** The free Eventbrite OAuth token returns HTTP 401 for the
retrieval endpoint — the token may need the `event_read:private` scope or a higher
access tier. 401/403/404 are handled silently (debug-level log only); the pipeline
continues normally with zero enriched events.

### `pipeline/normalize.py`

Ports the `normalizeEvent` / `parseDates` / `inferEventType` / `organicsToEvents` logic
from `index.html` into Python. `parse_dates()` handles Eventbrite ISO strings, Serper
human-readable strings (`"Apr 18 – 19, 2026"`), and date dicts; returns
`(start_date, end_date)` as `YYYY-MM-DD`. `infer_event_type()` classifies into one of
eight types using keyword matching against the query string + event title. `organics_to_events()`
filters Serper organic results by `ORGANIC_EVENT_RE`, extracts attendance, email/phone
contact, and cleans up title suffixes. `normalize_event()` produces an `EventItem` with
`county`/`city` left blank for `enrich()` to fill.

### `pipeline/enrich.py`

`Enricher` loads `zip-county.json` and `city-county.json` once at init and builds a
compiled county-name regex from `constants.COUNTIES` (longest names first, to prevent
partial matches). `enrich()` runs three tiers in sequence: (1) ZIP regex extraction
from `addr_full` → lookup in `zip-county.json`; (2) county name scanning of
`addr_full + venue + name` text via the compiled regex; (3) city extraction from
`addr_full` → lookup in `city-county.json`. Each tier tries the event's known state
first to resolve ambiguous county names like "Frederick" (exists in MD and VA) before
falling back to all states. First successful match wins.

### `pipeline/dedup.py`

Two-pass deduplication. `exact_dedup()` (pass 1) keys on
`normalized_name|year|locality` where locality is ZIP or state. On collision, the
higher-priority source wins (`eventbrite > serper_events > serper_organic`); ties break
on `page_score`. Missing fields (ZIP, county, city, venue) are merged from the
lower-priority duplicate. `fuzzy_merge_results()` (pass 2) buckets events by `year|county`
— not `startDate|zip` as in the original JS — so the same event with slightly different
parsed dates or missing ZIPs still lands in the same bucket. Within each bucket, events
with Jaccard token similarity >= 0.60 on their `normalize_for_dedup()` names are merged;
the loser's URL is appended to the winner's `sources[]` list. Events with no year and
no county are skipped from fuzzy comparison to prevent spurious cross-state merges.

### `pipeline/store.py`

`Store` wraps a SQLite connection in WAL mode. `upsert_events()` uses
`INSERT ... ON CONFLICT(event_id) DO UPDATE` — every upsert resets `synced=0` so the
sync step picks up refreshed data. `purge_expired()` deletes rows where `end_date` is
more than 30 days in the past. `get_unsynced()` returns up to 1000 `synced=0` rows as
dicts. `mark_synced()` sets `synced=1` for a list of `event_id`s. All writes use
`executemany`; errors roll back and raise `RuntimeError`. The `contact` column is stored
here but intentionally excluded from Meilisearch documents (see `sync.py`).

### `pipeline/sync.py`

`MeilisearchSync` configures the `events` index (idempotent — skips if already exists)
and applies the `_INDEX_SETTINGS` dict on every run. `sync_from_store()` reads unsynced
rows, converts them to camelCase Meilisearch documents via `_row_to_meili_doc()`, and
pushes in batches of 100. Each batch waits for task completion; if the task fails or
times out, `mark_synced` is skipped for that batch and it retries on the next pipeline
run. The `contact` field is excluded from `_row_to_meili_doc()` to prevent PII reaching
the search index. Meilisearch document field names are camelCase (`startDate`,
`countyFull`, `sourceType`, etc.) to match the existing frontend JS field names.

### `pipeline/models.py`

`EventItem` is a Python dataclass with default-empty fields. Identity: `event_id`
(SHA-256 of `dedup_key`) and `dedup_key`. Location: `venue`, `city`, `state`, `county`
(no suffix), `county_full` (with suffix), `zip`. Classification: `event_type` (one of
eight values). Provenance: `primary_url`, `source_type`, `source_queries: list[str]`,
`sources: list[dict]` (alternate URLs). Supplemental: `attendance`, `contact` (PII —
SQLite only). Pipeline bookkeeping: `page_score`, `fetched_at`, `synced`. The transient
field `addr_full` is used during enrichment and never persisted. `to_db_row()` produces
a flat dict with JSON-encoded list fields for SQLite storage.

### `pipeline/constants.py`

Defines `COUNTIES` (dict mapping state code → list of county/locality names),
`STATE_ORDER` (`["MD","VA","PA","NJ","DE","DC"]`), `STATE_NAMES` (code → full name),
and `EVENT_TYPES` (list of eight event type strings). These are the master lists used
throughout the pipeline for query generation, county name scanning, and Tier 3
city-to-county lookups. Edit here when adding new states or event types.

---

## 9. Security Notes

### Applied controls

| Control | What it does |
|---|---|
| MEILI_URL scheme validation | Startup rejects any URL not starting with `http://` or `https://` — prevents SSRF via env var injection |
| MEILI_MASTER_KEY placeholder check | Startup rejects key containing `"change-me"` — prevents accidental deploy with the example value |
| Eventbrite URL validation | `extract_eventbrite_id()` validates scheme (`https` only), host (exact match on `eventbrite.com`/`www.eventbrite.com`), path pattern, and ID format before calling the API — prevents lookalike-host injection and API calls on malformed URLs |
| Eventbrite response ID check | API response `id` field must match the requested ID; mismatches are logged and the enrichment is skipped — prevents applying data from the wrong event |
| `contact` PII exclusion | `sync.py._row_to_meili_doc()` omits `contact` — scraped emails/phones stay in SQLite only |
| Datasette internal-only network | `hiss-datasette` has no `ports:` mapping and is not on the proxy network — access requires SSH tunnel |
| Docker log rotation | `json-file` driver with `max-size: 10m` / `max-file: 3` on `hiss-pipeline` and `hiss-meilisearch` |
| Parameterized SQL | All SQLite queries use `?` placeholders; errors trigger `rollback()` |
| Per-batch Meilisearch error handling | Failed batches are skipped (not abort); they retry on the next pipeline run |
| Fuzzy dedup safety guard | Events with no year and no county are excluded from fuzzy comparison — prevents spurious cross-state merges of unresolved organics |

### Accepted risk (homelab — do not re-raise as blockers)

| Risk | Justification |
|---|---|
| Meilisearch port 7700 bound to all interfaces | Intentional — LAN browser access requires direct host port; no NPM proxy for search queries |
| `MEILI_MASTER_KEY` in Docker env vars | Standard Docker Compose limitation; `.env` is `chmod 600` and not committed |
| Base images not digest-pinned | Acceptable for homelab; simplifies updates |

---

## 10. Phase 1: Frontend Migration

**Goal:** Replace the Serper.dev call path in `index.html` with Meilisearch queries.

### What to remove

These JS functions call Serper directly and should be removed:
`callSerper`, `organicsToEvents`, `buildAllQueries`, `buildQueriesForState`,
`normalizeEvent`, `parseDates`, `inferEventType`, `dedupeKey`, `normalizeForDedup`,
`jaccardSimilarity`, `fuzzyMergeResults`, `enrich`.

Also remove: the Serper API key input field and the per-query progress display.

### What to add

- `searchMeilisearch(query, filters)` — calls `POST http://192.168.2.148:7700/indexes/events/search`
  with `Authorization: Bearer <MEILI_SEARCH_KEY>`. The search-only key is safe to embed
  in frontend JS (it can only read, not write).
- A "last updated" timestamp sourced from `GET /indexes/events/stats` (`lastUpdate`
  field) replacing the API key input.

### What to keep unchanged

- `renderResults()`, `applyFilters()`, `sortResults()`, `exportCSV()`
- All served-county modal code and localStorage (`hiss.servedCounties`)
- The served/unserved/unknown color-coding logic — it drives from `county` and `state`
  fields which are already in Meilisearch documents

### Meilisearch query shape

```json
{
  "q": "<user text input>",
  "filter": "state = MD AND eventType = 'Home Show'",
  "facets": ["state", "county", "eventType"],
  "sort": ["startDate:asc"],
  "limit": 200
}
```

Use `facets` to drive the state/county/event-type filter dropdowns. Served-county
filtering remains client-side JS (comparing `county`+`state` against `hiss.servedCounties`
in localStorage) — no change needed there.

### Browser access

The coordinator's browser hits `http://192.168.2.148:7700` directly. No HTTPS within
the homelab LAN is required for this use case (read-only public event data, no auth,
no PII in Meilisearch). `MEILI_SEARCH_KEY` is hardcoded in `index.html` at build/deploy
time or sourced from a `<script>` config block.

---

## 11. Key Constraints

- **Ease of use is paramount.** The end user is not technical. The tool must work by
  opening a browser. No terminal, no installs, no configuration files to edit.
- **County and ZIP are non-negotiable.** These fields drive the served/unserved
  filtering that is the entire point of the tool. Every event must have county resolved
  via the three-tier pipeline or clearly marked unknown.
- **No per-event fees.** The tool exists to escape FestivalNet's per-result pricing.
  Do not introduce any API with per-event or per-result billing.
- **contact field is SQLite-only.** Scraped emails and phone numbers must never reach
  Meilisearch — they are stored only in `hiss.db` for potential future use.
- **Meilisearch document fields are camelCase.** The existing `renderResults()` JS reads
  `startDate`, `countyFull`, `sourceType`, etc. Do not change the field names in
  `sync.py._row_to_meili_doc()` without updating the frontend to match.
- **Eventbrite is a best-effort enrichment layer.** The Discovery API (Tier 1) requires
  enterprise access and currently returns 404 on the free tier. The URL Retrieval API
  (used by `eventbrite_enrich.py`) requires a token with retrieval scope — the current
  free token returns 401. Both are handled silently; the pipeline always continues with
  Serper.dev as the sole data source. Do not treat Eventbrite failures as blocking errors.
- **Do not start Phase 2 (Scrapy) without explicit instruction.** `pipeline/spiders/`
  exists as a placeholder only.
