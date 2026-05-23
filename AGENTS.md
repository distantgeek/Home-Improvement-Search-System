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
│       ├── pipeline-publish.yml     # Builds pipeline image when pipeline/**,
│       │                            #   data/**, or Dockerfile.pipeline changes
│       └── codeql.yml               # CodeQL JS analysis: weekly + on push/PR to main
├── data/
│   ├── zip-county.json              # ZIP → {state, county} (~3,940 entries, VA/MD/PA/DC/NJ/DE)
│   └── city-county.json             # "STATE:city" → {county} (~3,822 entries)
├── docs/
│   ├── architecture.md              # Detailed architecture doc (superseded by this file)
│   └── county-coverage.md           # Served-county localStorage schema and UI notes
├── scripts/
│   ├── build-zip-county.sh          # Regenerates zip-county.json + city-county.json
│   │                                #   from U.S. Census ZCTA-to-County/Place files
│   ├── lint.sh                      # Runs ESLint on index.html (npx eslint)
│   ├── retire.sh                    # Runs Retire.js — vulnerable JS library detection (OWASP A06)
│   ├── sast.sh                      # Runs Semgrep via podman (p/javascript, p/owasp-top-ten,
│   │                                #   p/xss, p/secrets); output: sast-results.json (gitignored)
│   └── test-container.sh            # Runs Playwright E2E tests in podman container
├── tests/
│   ├── e2e/
│   │   ├── smoke.spec.js            # Basic app load and render checks
│   │   ├── search.spec.js           # Search flow assertions
│   │   ├── coverage.spec.js         # Served-county modal and colour-coding
│   │   └── export.spec.js           # CSV export
│   └── fixtures/
│       └── meili-results.json       # Mock Meilisearch response for E2E tests
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
├── eslint.config.mjs                # ESLint 9 flat config: security + no-unsanitized + html plugins
├── playwright.config.js             # Playwright E2E config; test dir: tests/e2e/
├── package.json                     # Dev dependencies + npm scripts (lint, sast, retire, test, audit:all)
├── package-lock.json                # Locked dependency tree
├── .npmrc                           # save-exact=true, package-lock=true, audit=true
├── index.html                       # Complete frontend app (currently calls Serper directly)
├── AGENTS.md                        # This file — primary agent context document
├── README.md                        # Human-readable setup and usage
└── LICENSE
```

---

## 4. Current State

### Phase 0 — COMPLETE ✓

All four services deployed and healthy on TrueNAS (`192.168.2.148`).
**127/127 tests pass** (`python3 -m pytest pipeline/tests/`).

| Service | State |
|---|---|
| `hiss` (frontend, port 8888) | Up — serving `index.html` via httpd:alpine |
| `hiss-meilisearch` (port 7700) | Up + healthy — 980+ events indexed |
| `hiss-pipeline` | Up — last ran successfully, next run Sunday 3am |
| `hiss-datasette` (internal, port 8001) | Up — immutable mode, SSH tunnel for access |

Completed work:
- `pipeline/` package — all modules implemented, including `eventbrite_enrich.py`
- `Dockerfile.pipeline` — python:3.12-slim, non-root `pipeline` user (UID 1000)
- `docker-compose.yml` — four services, internal network, log rotation, healthcheck
- `.env.example` — template with all required variables
- `.github/workflows/pipeline-publish.yml` — CI auto-build on relevant path changes
- `data/zip-county.json` + `data/city-county.json` — Census-derived lookup tables
- `MEILI_SEARCH_KEY` — Meilisearch auto-generated default search-only key; value is
  in `.env` on TrueNAS. Safe to embed in frontend HTML (search-only, cannot write).
- Volume permissions fixed (`pipeline_data` chowned to UID 1000)
- Datasette opened in immutable mode (`-i`) — no WAL lock file writes needed

The existing frontend (`index.html`) still calls Serper.dev directly from the browser.
Phase 0 was purely additive; the coordinator's workflow is unchanged.

### Pre-Phase-1 toolchain — COMPLETE ✓

Committed as `00b55f4` on `main`.

- **JS static analysis toolchain added:** ESLint 9 flat config (`eslint.config.mjs`) with
  `eslint-plugin-security` (OWASP A03 rules), `eslint-plugin-no-unsanitized` (XSS
  prevention), and `eslint-plugin-html` (processes inline `<script>` tags in `index.html`).
  Retire.js added for OWASP A06 vulnerable library detection. Semgrep runs via podman
  container (`docker.io/semgrep/semgrep:latest`) with `p/javascript`, `p/owasp-top-ten`,
  `p/xss`, and `p/secrets` rulesets.
- **CodeQL added:** `.github/workflows/codeql.yml` — GitHub Actions analysis of JavaScript
  with `security-extended,security-and-quality` query suite, triggered weekly and on
  push/PR to `main`.
- **Playwright E2E scaffold in place:** `playwright.config.js` + 4 spec files
  (`smoke`, `search`, `coverage`, `export`) under `tests/e2e/`. Tests run in the
  `mcr.microsoft.com/playwright:v1.60.0-noble` container via podman (`npm test`).
  `tests/fixtures/meili-results.json` provides a mock Meilisearch response.
- **Supply chain audit completed:** Full 22-check audit performed per CISA Shai-Hulud
  alert (2025-09-23) — IOC hash scanning, postinstall script audit, `npm audit`,
  `npm audit signatures`, and SLSA provenance attestation (Playwright verified).
  All packages clean.
- **`index.html` security fixes applied:** ESLint result: 0 errors, 7 accepted warnings.
  Fixes: removed dead `geocoderCache` variable, removed debug logging block, fixed
  unnecessary regex escapes, used optional catch binding, added `escHtml()` in county
  selector and coverage modal rendering, added `VALID_SOURCES` whitelist before
  source-pill class interpolation, renamed `showError(html)` param to `showError(msg)`.
  7 remaining warnings are accepted false positives (complex regex detection, one dynamic
  regex built from the trusted `COUNTIES` constant).
- **Fedora atomic constraint:** This devbox runs Fedora bootc — `dnf install` is not
  available at runtime. All JS tooling must be npm packages (project `node_modules`) or
  containerized via podman. This constraint applies to all future tooling additions.

### Phase 1 — NEXT (ready to start)

Migrate `index.html` to query Meilisearch instead of Serper.dev.
**See Section 10 for the complete spec and kickoff checklist.**

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

### Updating images after a push to main

```bash
# Pull and restart a specific service (e.g. after a pipeline code change)
ssh truenas "sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml pull hiss-pipeline && sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml up -d hiss-pipeline"

# Pull and restart the frontend after index.html changes
ssh truenas "sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml pull hiss && sudo docker compose -f /mnt/kevbot-store/stacks/home-improvement-show-search/compose.yaml up -d hiss"
```

The pipeline image rebuilds when `pipeline/**`, `data/**`, or `Dockerfile.pipeline` change.
The frontend image rebuilds on any push to `main` (watches `Dockerfile` and `index.html`).

### Datasette access (debug only)

Datasette is internal-only (no host port binding). SSH tunnel to browse `hiss.db`:

```bash
ssh -L 8001:localhost:8001 truenas -N &
# then open http://localhost:8001/ in a browser
# kill %1 when done
```

Note: Datasette runs in immutable mode (`-i /data/hiss.db`) — it cannot write to the
database. This prevents lock-file conflicts with the pipeline's WAL-mode SQLite writes.

### Verify Meilisearch index

Meilisearch requires auth — use the master key for admin queries:

```bash
MEILI_KEY=$(ssh truenas "sudo grep MEILI_MASTER_KEY /mnt/kevbot-store/stacks/home-improvement-show-search/.env | cut -d= -f2")
ssh truenas "curl -s http://192.168.2.148:7700/indexes/events/stats -H \"Authorization: Bearer $MEILI_KEY\""
# numberOfDocuments should be 950–1050 after a successful pipeline run
```

### First deployment (reference — already done; skip this section)

1. Copy `compose.yaml` + `.env` to `/mnt/kevbot-store/stacks/home-improvement-show-search/`.
   The TrueNAS `compose.yaml` uses `ports: "8888:80"` on `hiss` (NPM routes by host IP).
2. Set `MEILI_MASTER_KEY`, `SERPER_API_KEY`, `EVENTBRITE_API_KEY` in `.env`. `chmod 600 .env`.
3. Fix volume ownership: `sudo docker run --rm -v home-improvement-show-search_pipeline_data:/data busybox chown -R 1000:1000 /data`
4. Start: `sudo docker compose -f compose.yaml up -d`
5. `MEILI_SEARCH_KEY` is auto-generated by Meilisearch on first start as "Default Search API Key".
   Retrieve it: `curl -s http://192.168.2.148:7700/keys -H "Authorization: Bearer $MEILI_MASTER_KEY"`
   Add it to `.env` for Phase 1 frontend embedding.

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

### Frontend (JavaScript) QA

All JS tooling runs via `npm` scripts (no `dnf install` — Fedora atomic constraint).
Semgrep and Playwright run inside podman containers; ESLint and Retire.js run via `npx`.

```bash
# Lint index.html inline scripts (ESLint, OWASP rules)
npm run lint

# SAST scan (Semgrep via podman — p/javascript, p/owasp-top-ten, p/xss, p/secrets)
npm run sast
# Output written to sast-results.json (gitignored)

# Vulnerable library detection (Retire.js, OWASP A06)
npm run retire

# Supply chain verification (npm audit + npm audit signatures)
npm run verify

# All QA checks in one shot
npm run audit:all

# E2E tests (Playwright in mcr.microsoft.com/playwright:v1.60.0-noble via podman)
npm test
```

**Accepted warnings (do not re-raise as blockers):**
The 7 ESLint warnings remaining after the pre-Phase-1 fixes are false positives:
complex regexes flagged by `detect-unsafe-regex`, and one dynamic regex built from
the trusted `COUNTIES` constant. All are marked with `// eslint-disable-next-line`
comments and justification in `index.html`.

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

### Frontend security controls

| Control | What it does |
|---|---|
| ESLint OWASP ruleset | `eslint-plugin-security` + `eslint-plugin-no-unsanitized` + `eslint-plugin-html` scan `index.html` inline scripts for OWASP A03/XSS patterns |
| Semgrep SAST | `p/javascript`, `p/owasp-top-ten`, `p/xss`, `p/secrets` rules via podman container — 0 findings on current codebase |
| Retire.js | OWASP A06 — scans for vulnerable JS library versions referenced in `index.html` |
| CodeQL | GitHub Actions: weekly + on push/PR to `main`; `security-extended,security-and-quality` queries on JavaScript |
| Supply chain audit | npm audit + npm audit signatures + SLSA provenance verification per CISA Shai-Hulud (2025-09-23) advisory |

### Accepted risk (homelab — do not re-raise as blockers)

| Risk | Justification |
|---|---|
| Meilisearch port 7700 bound to all interfaces | Intentional — LAN browser access requires direct host port; no NPM proxy for search queries |
| `MEILI_MASTER_KEY` in Docker env vars | Standard Docker Compose limitation; `.env` is `chmod 600` and not committed |
| Base images not digest-pinned | Acceptable for homelab; simplifies updates |

---

## 10. Phase 1: Frontend Migration

> **Starting Phase 1?** Read this section top-to-bottom before touching any code.
> Everything you need is here — no discovery work required.

**Goal:** Replace the Serper.dev call path in `index.html` with Meilisearch queries.
The backend already has the data. The frontend just needs to ask Meilisearch instead of
calling Serper directly from the browser.

### Credentials and endpoints

| Item | Value |
|---|---|
| Meilisearch host | `http://192.168.2.148:7700` |
| Search-only key | `REDACTED_MEILI_KEY` |
| Search endpoint | `POST http://192.168.2.148:7700/indexes/events/search` |
| Stats endpoint | `GET http://192.168.2.148:7700/indexes/events/stats` |
| Auth header | `Authorization: Bearer REDACTED_MEILI_KEY` |

The search-only key has `actions: ["search"]` only — it cannot write, delete, or
configure the index. Safe to hardcode in `index.html`.

### Meilisearch document schema

Every document in the `events` index has these fields (all camelCase — the existing
`renderResults()` JS already uses these names):

```
eventId        dedupeKey      name           startDate      endDate
venue          city           state          county         countyFull
zip            eventType      primaryUrl     sourceType     sourceQueries
sources        attendance     pageScore      fetchedAt
```

`contact` is intentionally absent — PII stays in SQLite only.

### Search query shape

```javascript
// POST http://192.168.2.148:7700/indexes/events/search
{
  "q": "",                          // empty = return all; user text = full-text search
  "filter": "state = 'MD'",        // optional filter expression
  "facets": ["state", "county", "eventType"],
  "sort": ["startDate:asc"],
  "limit": 500,
  "attributesToRetrieve": ["*"]
}
```

Filter syntax examples:
```
state = 'MD'
state = 'MD' AND eventType = 'Home Show'
state IN ['MD', 'VA'] AND startDate >= '2026-01-01'
```

### What to remove from index.html

These functions call Serper.dev and implement the pipeline logic that now lives in the
backend. Delete them entirely:

```
callSerper()          buildAllQueries()      buildQueriesForState()
organicsToEvents()    normalizeEvent()       parseDates()
inferEventType()      dedupeKey()            normalizeForDedup()
jaccardSimilarity()   fuzzyMergeResults()    enrich()
```

Also remove:
- The Serper API key `<input>` field and its localStorage save/load logic
- The per-query progress counter and "Built N queries" display
- The stop-button logic (no long-running query loop to stop)
- The `COUNTIES`, `STATE_NAMES`, `STATE_ORDER` JS constants (pipeline owns these now)

### What to add

**`searchMeilisearch(query, filters)`** — replaces `callSerper` as the data source:

```javascript
async function searchMeilisearch(query = "", filters = {}) {
  const MEILI_URL = "http://192.168.2.148:7700";
  const MEILI_KEY = "REDACTED_MEILI_KEY";

  const body = {
    q: query,
    limit: 500,
    sort: ["startDate:asc"],
    facets: ["state", "county", "eventType"],
  };
  if (filters.state)     body.filter = `state = '${filters.state}'`;
  if (filters.eventType) body.filter = (body.filter ? body.filter + " AND " : "") + `eventType = '${filters.eventType}'`;

  const resp = await fetch(`${MEILI_URL}/indexes/events/search`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${MEILI_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`Meilisearch error ${resp.status}`);
  const data = await resp.json();
  return data.hits;   // array of event documents
}
```

**"Last updated" banner** — replace the API key input with a data freshness indicator:

```javascript
async function fetchLastUpdated() {
  const resp = await fetch("http://192.168.2.148:7700/indexes/events/stats", {
    headers: { "Authorization": "Bearer REDACTED_MEILI_KEY" }
  });
  const stats = await resp.json();
  // stats.numberOfDocuments, stats.isIndexing
  return stats;
}
```

### What to keep unchanged

- `renderResults(events)` — already reads camelCase field names from event objects
- `applyFilters()`, `sortResults()`, `exportCSV()`
- All served-county modal code and `localStorage` (`hiss.servedCounties`)
- The served/unserved/unknown colour-coding logic — reads `county` + `state` fields
  which are already in every Meilisearch document

### Implementation order

1. Read `index.html` in full to understand the current structure before touching anything.
2. Add `searchMeilisearch()` and `fetchLastUpdated()` — test they return data before
   removing anything.
3. Wire `searchMeilisearch()` to the search button handler. Confirm results render.
4. Remove Serper-specific code (functions listed above, API key input, progress UI).
5. Replace the API key input section with the "last updated" / doc count display.
6. Update the filter dropdowns to be driven by Meilisearch `facetDistribution` rather
   than the hardcoded county/state constants.
7. Test: empty search (all events), text search, state filter, county filter, CSV export,
   served-county modal, served/unserved filtering.
8. Build and push: `git push origin main` triggers the frontend image rebuild.
9. Pull and restart `hiss` on TrueNAS to deploy.

### Testing during development

The frontend is a single static file. Run a local server to avoid CORS issues with
the Meilisearch fetch:

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Meilisearch at `192.168.2.148:7700` is reachable from any LAN client — no tunnel needed
for browser-to-Meilisearch calls. Datasette SSH tunnel is only needed for direct SQLite
inspection.

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
