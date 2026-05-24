# HISS Architecture: Data Pipeline + Search Backend

## Overview

HISS migrates from a single-file browser app that calls Serper.dev directly to a
scheduled data pipeline that pre-fetches, normalizes, deduplicates, and indexes events
into Meilisearch. The frontend becomes a thin search UI against the local Meilisearch
instance. The coordinator's workflow is unchanged — open browser, results are already
there.

---

## Stack

| Technology | Role | Notes |
|---|---|---|
| **Python 3.12** | Pipeline runtime | requests, BeautifulSoup4, rapidfuzz, meilisearch |
| **Eventbrite Discovery API** | Tier 1 event source | Structured: venue, ZIP, dates in response; API key in `.env` |
| **Serper.dev** | Tier 2 catch-all | Google Events + organic fallback; 2,500/mo free; existing codebase |
| **BeautifulSoup4** | Organic fallback parsing | Parses Serper organic snippets; Scrapy reserved for Phase 2 |
| **APScheduler** | Container-internal cron | Pipeline runs weekly inside the container; no host cron |
| **SQLite** | Canonical data store | Source of truth; pipeline writes here first |
| **Meilisearch v1.x** | Search index | Typo-tolerant, faceted REST search; port 7700 exposed on TrueNAS host |
| **Datasette** | Admin/debug UI | Read-only browse of `hiss.db`; useful for verifying dedup output |
| **rapidfuzz** | Jaccard similarity | Python port of fuzzyMergeResults; C extension, faster than pure Python |
| **nginx:alpine** | Frontend static server + reverse proxy | Serves `index.html`; proxies `/meili/` to Meilisearch with server-side auth header |
| **Scrapy** | Phase 2 curated crawling | Multi-domain HTML crawlers for state fair sites, home show org pages |
| **Docker Compose** | Service orchestration | Dockge on TrueNAS manages the stack |
| **GHCR** | Container registry | Existing CI/CD; pipeline image added |

**Rejected alternatives:**
- SerpAPI: different endpoint/format, more expensive, fewer free searches
- Elasticsearch: JVM overhead, overkill for homelab
- PostgreSQL: unnecessary dependency for ~5,000 event records
- Solr: JVM overkill
- Algolia/Typesense Cloud: per-operation billing
- Host-level cron: anti-pattern when everything is containerized

---

## Network Topology

```
Browser (LAN coordinator machine)
  │
  └── http://truenas-ip:8888  →  hiss (nginx:alpine) → /meili/ → Meilisearch

TrueNAS Docker internal network
  hiss-pipeline ──→ hiss-meilisearch:7700  (index writes, master key)
  hiss-pipeline ──→ hiss-datasette:8001    (shared SQLite volume)
  hiss-pipeline ──→ /data/hiss.db          (named volume)
```

Meilisearch is proxied through the nginx frontend container at `/meili/`. The
Authorization header is injected server-side from a Docker secret file — the API key
never reaches the browser. Port 7700 may also be exposed on the TrueNAS host for direct
debug access. No HTTPS within the homelab LAN is acceptable for this use case.

---

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  hiss-pipeline container  (APScheduler: weekly)                      │
│                                                                      │
│  ┌────────────────────┐    ┌─────────────────────────────────────┐   │
│  │  TIER 1            │    │  TIER 2                             │   │
│  │  Eventbrite API    │    │  Serper.dev                         │   │
│  │  fetchers/         │    │  fetchers/serper.py                 │   │
│  │  eventbrite.py     │    │                                     │   │
│  │                    │    │  POST google.serper.dev/search      │   │
│  │  GET /events/      │    │  eventsResults[] → structured       │   │
│  │  search/?q=...     │    │  organic[]      → organicsToEvents  │   │
│  │  &location=...     │    │                                     │   │
│  └─────────┬──────────┘    └──────────────┬──────────────────────┘   │
│            │                              │                           │
│            └──────────────┬──────────────┘                           │
│                           ▼                                           │
│             ┌─────────────────────────┐                              │
│             │  normalize.py           │                              │
│             │  normalizeEvent()       │                              │
│             │  parseDates()           │                              │
│             │  inferEventType()       │                              │
│             └──────────┬──────────────┘                              │
│                        ▼                                              │
│             ┌─────────────────────────┐                              │
│             │  enrich.py              │                              │
│             │  Tier 1: ZIP regex      │                              │
│             │    → zip-county.json    │                              │
│             │  Tier 2: county name    │                              │
│             │    regex scan           │                              │
│             │  Tier 3: city lookup    │                              │
│             │    → city-county.json   │                              │
│             └──────────┬──────────────┘                              │
│                        ▼                                              │
│             ┌─────────────────────────┐                              │
│             │  dedup.py               │                              │
│             │  Pass 1 (exact):        │                              │
│             │    name|year|locality   │                              │
│             │  Pass 2 (fuzzy):        │                              │
│             │    bucket: year|county  │ ← fixed (was startDate|zip) │
│             │    Jaccard ≥ 0.60       │                              │
│             │    sources[] accumulate │                              │
│             └──────────┬──────────────┘                              │
│                        ▼                                              │
│             ┌─────────────────────────┐                              │
│             │  store.py               │                              │
│             │  SQLite UPSERT          │                              │
│             │  on event_id (SHA-256   │                              │
│             │  of dedup key)          │                              │
│             │  purge rows where       │                              │
│             │  end_date < today-30d   │                              │
│             └──────────┬──────────────┘                              │
│                        ▼                                              │
│             ┌─────────────────────────┐                              │
│             │  sync.py                │                              │
│             │  Read synced=0 rows     │                              │
│             │  → Meilisearch          │                              │
│             │  add_documents()        │                              │
│             │  Mark synced=1          │                              │
│             └─────────────────────────┘                              │
└──────────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────▼───────────────┐
              │  hiss-meilisearch              │
              │  Meilisearch v1.x              │
              │  port 7700 (host-exposed)      │
              │  index: "events"               │
              │  search-only key → index.html  │
              └────────────────────────────────┘
```

---

## EventItem Schema

Canonical Python dataclass that flows through the entire pipeline.

```python
@dataclass
class EventItem:
    # Identity
    event_id: str          # SHA-256 hex of dedup_key
    dedup_key: str         # "normalized_name|year|locality"

    # Core
    name: str
    start_date: str        # "YYYY-MM-DD" or ""
    end_date: str          # "YYYY-MM-DD", defaults to start_date

    # Location
    venue: str
    city: str
    state: str             # VA|MD|PA|DC|NJ|DE
    county: str            # "Frederick" (no suffix)
    county_full: str       # "Frederick County"
    zip: str               # 5-digit or ""

    # Classification
    event_type: str        # Home Show|Home & Garden|County Fair|State Fair|
                           # Art & Craft|Food Festival|Fall Festival|Community Festival

    # Provenance
    primary_url: str       # Eventbrite > Serper events > Serper organic
    source_type: str       # "eventbrite"|"serper_events"|"serper_organic"
    source_queries: list[str]
    sources: list[dict]    # Alternate URLs: [{"url": "...", "source_type": "..."}]

    # Supplemental
    attendance: str
    contact: str

    # Pipeline bookkeeping
    page_score: int
    fetched_at: str        # ISO 8601 UTC
    synced: int            # 0 = needs Meilisearch sync, 1 = synced
```

**Source priority (highest wins for `primary_url`):**
1. `eventbrite` — structured, canonical URL, venue/ZIP in response directly
2. `serper_events` — Google Events carousel result
3. `serper_organic` — parsed from organic search result

**Meilisearch documents use camelCase** (`startDate`, `countyFull`, `sourceType`, etc.)
to match the existing frontend JS field names, avoiding a rewrite of `renderResults()`.

---

## Directory Structure

```
home-improvement-search-system/
├── .github/workflows/
│   ├── docker-publish.yml       # existing: hiss frontend image
│   └── pipeline-publish.yml     # NEW: hiss-pipeline image
├── data/
│   ├── zip-county.json          # existing
│   └── city-county.json         # existing
├── docs/
│   ├── architecture.md          # this file
│   └── county-coverage.md       # existing
├── scripts/
│   └── build-zip-county.sh      # existing
├── pipeline/
│   ├── __init__.py
│   ├── requirements.txt
│   ├── models.py                # EventItem dataclass
│   ├── normalize.py             # normalizeEvent, parseDates, inferEventType
│   ├── enrich.py                # three-tier county/ZIP enrichment
│   ├── dedup.py                 # dedupeKey, normalizeForDedup, jaccardSimilarity,
│   │                            # fuzzyMergeResults (year|county bucket fix)
│   ├── store.py                 # SQLite UPSERT + 30-day purge
│   ├── sync.py                  # dirty rows → Meilisearch + index config
│   ├── run.py                   # entry point: orchestrate + APScheduler
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── eventbrite.py        # Tier 1: Eventbrite Discovery API
│   │   └── serper.py            # Tier 2: Serper.dev + organicsToEvents
│   ├── spiders/                 # Phase 2 only (Scrapy)
│   │   └── .gitkeep
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_normalize.py
│       ├── test_enrich.py
│       ├── test_dedup.py
│       ├── test_store.py
│       ├── test_sync.py
│       └── fixtures/
│           ├── serper_events_response.json
│           ├── serper_organic_response.json
│           └── eventbrite_response.json
├── Dockerfile                   # existing: nginx:alpine frontend + reverse proxy
├── Dockerfile.pipeline          # NEW: Python pipeline image
├── docker-compose.yml           # MODIFIED: adds 3 new services
├── .env.example                 # NEW: template for required env vars
├── index.html                   # MODIFIED in Phase 1: queries Meilisearch
├── AGENTS.md
└── README.md
```

---

## Docker Compose Services

```yaml
services:

  # Unchanged
  hiss:
    image: ghcr.io/distantgeek/home-improvement-search-system:latest
    container_name: hiss
    restart: unless-stopped
    ports:
      - "8888:80"
    networks:
      - proxy

  # NEW: Meilisearch
  hiss-meilisearch:
    image: getmeili/meilisearch:v1.13
    container_name: hiss-meilisearch
    restart: unless-stopped
    ports:
      - "7700:7700"          # exposed on TrueNAS host; browser calls directly
    environment:
      MEILI_ENV: production
      MEILI_MASTER_KEY: "${MEILI_MASTER_KEY}"
      MEILI_MAX_INDEXING_MEMORY: 128Mb
    volumes:
      - meilisearch_data:/meili_data
    networks:
      - internal

  # NEW: Pipeline (long-lived, APScheduler runs weekly internally)
  hiss-pipeline:
    image: ghcr.io/distantgeek/home-improvement-search-system/pipeline:latest
    container_name: hiss-pipeline
    restart: unless-stopped
    environment:
      SERPER_API_KEY: "${SERPER_API_KEY}"
      EVENTBRITE_API_KEY: "${EVENTBRITE_API_KEY}"
      MEILI_URL: "http://hiss-meilisearch:7700"
      MEILI_MASTER_KEY: "${MEILI_MASTER_KEY}"
      MEILI_SEARCH_KEY: "${MEILI_SEARCH_KEY}"
      DB_PATH: "/data/hiss.db"
      PIPELINE_SCHEDULE: "0 3 * * 0"   # weekly, Sunday 3am
    volumes:
      - pipeline_data:/data
      - ./data:/app/data:ro             # zip-county.json, city-county.json
    networks:
      - internal
    depends_on:
      - hiss-meilisearch

  # NEW: Datasette (debug/admin, read-only)
  hiss-datasette:
    image: datasetteproject/datasette:latest
    container_name: hiss-datasette
    restart: unless-stopped
    command: >
      datasette /data/hiss.db
      --host 0.0.0.0 --port 8001
      --setting sql_time_limit_ms 5000
      --setting max_returned_rows 500
    volumes:
      - pipeline_data:/data:ro
    networks:
      - proxy
      - internal

volumes:
  meilisearch_data:
  pipeline_data:

networks:
  proxy:
    external: true
    name: "${NPM_NETWORK_NAME}"
  internal:
    driver: bridge
```

`.env.example`:
```
MEILI_MASTER_KEY=change-me-min-16-chars
MEILI_SEARCH_KEY=           # populated after first deploy: POST /keys with actions=["search"]
SERPER_API_KEY=
EVENTBRITE_API_KEY=
NPM_NETWORK_NAME=           # your NPM external Docker network name
```

---

## Meilisearch Index Settings

Index name: `events` | Primary key: `id`

```json
{
  "filterableAttributes": [
    "state", "county", "countyFull", "eventType",
    "startDate", "endDate", "zip", "sourceType"
  ],
  "sortableAttributes": ["startDate", "name", "county"],
  "searchableAttributes": [
    "name", "venue", "city", "county", "eventType", "attendance"
  ],
  "typoTolerance": {
    "enabled": true,
    "minWordSizeForTypos": { "oneTypo": 5, "twoTypos": 9 },
    "disableOnAttributes": ["zip", "startDate", "endDate"]
  },
  "faceting": { "maxValuesPerFacet": 100 },
  "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"]
}
```

---

## Migration Phases

### Phase 0 — Pipeline (no frontend change)

Build the entire pipeline and deploy it alongside the existing app. The coordinator
continues to use the current `index.html` unchanged. This phase is purely additive.

Deliverables: `pipeline/` modules, unit tests, `Dockerfile.pipeline`,
`hiss-meilisearch` + `hiss-pipeline` + `hiss-datasette` services in
`docker-compose.yml`, Meilisearch populated with real data.

### Phase 1 — Frontend cutover

Modify `index.html` to query Meilisearch instead of calling Serper.dev directly.
Remove: `callSerper`, `organicsToEvents`, `buildAllQueries`, `buildQueriesForState`,
`normalizeEvent`, `parseDates`, `inferEventType`, `dedupeKey`, `normalizeForDedup`,
`jaccardSimilarity`, `fuzzyMergeResults`, `enrich`.
Add: `searchMeilisearch(query, filters)` using the search-only key.
Keep: `renderResults`, `applyFilters`, `sortResults`, `exportCSV`, all served-county
modal code, all localStorage.

The Serper API key input field is removed from the UI. A "last updated" timestamp
(from Meilisearch index stats) replaces it.

### Phase 2 — Scrapy curated sources

Add Scrapy spiders for curated sources: state fair official sites, home show
association pages, regional event aggregators. These produce clean `EventItem`-
compatible dicts fed into the same normalize → enrich → dedup → store → sync chain.
Serper.dev remains as catch-all for discovery.

---

## Phase 0 Implementation Checklist

**Setup**
- [ ] `pipeline/__init__.py`, `pipeline/requirements.txt`
- [ ] `pipeline/models.py` — `EventItem` dataclass + `make_event_id(dedup_key)`

**Tests scaffold**
- [ ] `pipeline/tests/conftest.py` — `tmp_db` fixture, sample API response fixtures

**Normalization (port from index.html)**
- [ ] `normalize.py`: `parseDates()`, `inferEventType()`, `normalizeEvent()`
- [ ] `tests/test_normalize.py` — edge cases: range dates, missing year, ISO from Eventbrite

**Enrichment (port from index.html)**
- [ ] `enrich.py`: three-tier `enrich(event)` loading zip-county.json + city-county.json
- [ ] `tests/test_enrich.py` — known ZIP→county assertions (e.g. `21701` → Frederick County MD)

**Deduplication (port from index.html, with bucket fix)**
- [ ] `dedup.py`: `dedupeKey()`, `normalizeForDedup()`, `jaccardSimilarity()`,
      `fuzzyMergeResults()` with `year|county` bucket key
- [ ] `tests/test_dedup.py` — same event two queries → merged; different events → not merged;
      `sources[]` accumulation

**SQLite store**
- [ ] `store.py`: `init_db()`, `upsert_events()`, `purge_expired()` (end_date < today-30d)
- [ ] `tests/test_store.py` — UPSERT idempotency, purge behavior

**Fetchers**
- [ ] `fetchers/serper.py`: `callSerper()`, `organicsToEvents()`, `fetch_all()` with
      400ms inter-query delay and 429 backoff
- [ ] `tests/test_serper.py` — mock `requests.post`
- [ ] `fetchers/eventbrite.py`: Discovery API client with location + keyword search
- [ ] `tests/test_eventbrite.py` — mock responses

**Meilisearch sync**
- [ ] `sync.py`: `configure_index()` (idempotent settings), `sync_to_meilisearch()`
      (reads synced=0, upserts in batches of 100, marks synced=1)
- [ ] `tests/test_sync.py` — mock HTTP

**Orchestration**
- [ ] `run.py`: `load_config_from_env()`, `configure_index()`, build query list,
      run fetchers, normalize, enrich, dedup, store, sync; APScheduler weekly trigger;
      `--dry-run` flag for testing

**Docker + CI**
- [ ] `Dockerfile.pipeline`
- [ ] Update `docker-compose.yml` — add 3 services + volumes + internal network
- [ ] `.env.example`
- [ ] `pipeline-publish.yml` GitHub Actions workflow

**Validation**
- [ ] `python run.py --dry-run` — verify full chain, print sample events
- [ ] Full run → check `curl http://localhost:7700/indexes/events/stats`
- [ ] Verify dedup: known county fair appears once despite multiple matching queries
