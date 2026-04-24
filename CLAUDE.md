````markdown
# HISS Handoff: Sandbox → Local Claude Code CLI

**Context for Claude:** The previous development session ran inside the Claude Code Web research preview. Two commits worth of work (new stub files + an enriched project brief + a ZIP→county build script) exist only in that sandbox — the sandbox blocked `git push` with a 403 from its git proxy, and there was no way to export files out of it. This document recreates all of that work so you can commit and push it from a normal local environment.

## What exists on GitHub right now

- Repo: `git@github.com:distantgeek/home-improvement-search-system.git`
- Branch `main` has an initial commit.
- Branch `claude/review-claude-md-2RWSY` has one extra commit: `ddc09ff Baseline HTML plus CLAUDE Code handoff.` (adds `index.html` mock prototype + a previous shorter version of `CLAUDE.md`).

Your job is to add the files/edits below on top of `origin/claude/review-claude-md-2RWSY`, commit, push, then run `scripts/build-zip-county.sh` to generate `data/zip-county.json` and commit that too.

## Bootstrap

```bash
git clone git@github.com:distantgeek/home-improvement-search-system.git
cd home-improvement-search-system
git fetch origin
git checkout claude/review-claude-md-2RWSY
# The working tree should have: index.html, CLAUDE.md, LICENSE
```

## Files to create or overwrite

Create these files with the exact contents below. `CLAUDE.md` already exists but needs to be **overwritten** with the expanded version.

### `.gitignore` (new)

````
# OS
.DS_Store
Thumbs.db

# Editors
.vscode/
.idea/
*.swp
*.swo
*~

# Logs
*.log
npm-debug.log*

# Environment / secrets
.env
.env.local
*.key
secrets.json

# Build artifacts (none today, but just in case)
dist/
build/
node_modules/

# Scratch
tmp/
scratch/
````

### `README.md` (new)

````markdown
# Home Improvement Show Search (HISS)

Locally-run event discovery tool for home improvement companies that exhibit at trade shows, home expos, county fairs, and state fairs across VA, MD, PA, DC, and NJ.

See [CLAUDE.md](./CLAUDE.md) for the full project brief.

## Quick Start

1. Clone or download this repo.
2. Double-click `index.html` (or open it in any modern browser).
3. Paste your [Serper.dev](https://serper.dev) API key into the settings panel. The key is stored in your browser's localStorage — nothing is uploaded.
4. Pick the states, counties, and event categories you want to search.
5. Click **Search**. Results stream in query-by-query.
6. Use the **Served Counties** modal to mark which counties your company operates in. Events are then color-coded green (served) / red (not served) / gray (unconfigured).
7. Click **Export CSV** to download results.

## Requirements

- A modern browser (Chrome, Firefox, Safari, Edge).
- A free Serper.dev API key (2,500 searches/month).
- Internet connection while searching.

No install, no build step, no Node, no server.

## Data Sources

- **Event search:** Google Events via [Serper.dev](https://serper.dev).
- **ZIP → County enrichment:** U.S. Census Bureau ZCTA-to-County relationship file (public, free). Regenerate with `scripts/build-zip-county.sh`.

## Repository Layout

```
index.html              # The entire app
CLAUDE.md               # Project brief for Claude Code
README.md               # This file
docs/county-coverage.md # Notes on served-county configuration
scripts/                # Maintenance scripts (ZIP lookup build, etc.)
data/                   # Generated data (zip-county.json)
```

## Development

### Resuming in a fresh Claude Code session

This project is designed to be continued by Claude Code. When starting a new session:

1. **Read `CLAUDE.md`** — it's the authoritative project brief and the "What Needs to Be Built Next" section is the working TODO list.
2. **Generate `data/zip-county.json`** if it isn't already committed:
   ```bash
   ./scripts/build-zip-county.sh
   git add data/zip-county.json
   git commit -m "Regenerate ZIP→county lookup from Census 2020 data"
   ```
   The script downloads the U.S. Census ZCTA-to-County relationship file, filters it to VA/MD/PA/DC/NJ, and emits a compact JSON lookup. Requires `bash`, `curl`, `awk`, and `python3`. Runs in a few seconds on a normal connection — the fetch is the dominant cost; ~5 MB download, ~55k rows nationally, ~10–15k kept after filtering.
3. **Open `index.html`** in a browser to see the current mock-data prototype. The UI is built; the Serper API wiring is the next thing to implement.

### Branch conventions

Development work lives on feature branches under `claude/...`. The main branch tracks shippable state.

### Testing the frontend

Because `index.html` is pure static assets, two testing options:

- **Double-click:** opens via `file://`. Works for everything except `fetch('data/zip-county.json')` in some browsers (CORS restrictions on `file://`).
- **Local server** (preferred during development):
  ```bash
  python3 -m http.server 8000
  # then open http://localhost:8000/ in a browser
  ```

### What's next

See the **"What Needs to Be Built Next"** section of [`CLAUDE.md`](./CLAUDE.md) for the detailed build order and implementation notes (Serper request shape, localStorage key schema, dedup algorithm, error-handling rules).

## License

See [LICENSE](./LICENSE).
````

### `CLAUDE.md` (overwrite existing)

````markdown
# Home Improvement Show Search (HISS)
## Claude Code Project Brief

---

## What This Is

A locally-run event discovery tool for a home improvement company that exhibits at trade shows, home expos, county fairs, state fairs, and similar events. The company offers gutter protection, roofing, awnings, and related services.

**The problem it solves:** The event coordinator was manually printing lists from FestivalNet.com (a craft/art-vendor-focused platform with predatory per-event pricing) and hand-pruning results by county. That workflow is wrong for the use case and not scalable.

**The solution:** A single-file HTML frontend (locally launched, no install required) that queries Google Events data via the Serper.dev API, aggregates results across multiple targeted search queries, and exports a clean CSV with county and ZIP enrichment.

---

## Architecture Decisions

### Frontend
- **Single `index.html` file** — no build step, no Node, no install. The coordinator double-clicks it or opens it in a browser. That's it.
- Vanilla HTML/CSS/JS only. No frameworks.
- LocalStorage for persisting served county configuration between sessions.

### API
- **Serper.dev** (preferred over SerpAPI) for Google Events scraping
  - 2,500 free searches/month — sufficient for this use case
  - Simpler pricing, no legal controversy (SerpAPI is currently being sued by Google as of Dec 2025)
  - API key will be entered in the UI and stored in localStorage (not hardcoded)
- **U.S. Census Bureau public API / ZCTA relationship files** for ZIP → county enrichment (free, no key required, chosen over USPS address validation for this use case)

### Search Strategy
The tool runs multiple targeted queries per selected county to cover all event categories. Example for "Frederick County, MD":
```
"home show Frederick County Maryland"
"home improvement expo Frederick County Maryland"
"home and garden show Frederick Maryland"
"county fair Frederick Maryland"
"home remodeling expo Frederick Maryland"
```
Results are merged and deduplicated by event name + date.

---

## Geographic Scope

**States:** Virginia (VA), Maryland (MD), Pennsylvania (PA), Washington DC, New Jersey (NJ)

Full county lists are pre-loaded in the frontend for all 5 states/jurisdictions. DC is a single entry (District of Columbia).

**Key data fields required in every result:**
- County
- ZIP Code
- These are critical for the "served counties" filtering feature

---

## Served Counties Feature

The company does **not** operate in all counties. A configuration panel allows the coordinator to check off which counties they serve. This is stored in localStorage.

In search results:
- **Green indicator** = event is in a served county
- **Gray indicator** = county not yet configured
- **Red indicator** = event is outside service area

A filter toggle shows: All Results / Served Only / Not Served Only

**Note:** The actual list of served counties has not been provided yet. The feature must exist and be configurable, but no defaults should be assumed.

---

## Event Categories (Search Query Templates)

Each category maps to a set of search query patterns. The coordinator checks which categories to include:

| Category | Query Keywords |
|----------|---------------|
| Home Shows & Remodeling Expos | "home show", "home improvement expo", "remodeling expo" |
| Home & Garden Expos | "home and garden show", "home garden expo" |
| County Fairs | "county fair" |
| State Fairs | "state fair" |
| Art & Craft Shows | "art fair", "craft show", "art and craft festival" |

---

## Results Table Columns

| Column | Notes |
|--------|-------|
| Event Name | Linked to source URL |
| Dates | Start + end date |
| Venue | Name of venue/fairgrounds |
| City | City of event |
| County | **Required** — extracted or inferred |
| ZIP Code | **Required** — extracted or inferred |
| Event Type | Tag/badge (Home Show, County Fair, etc.) |
| In Service Area? | ✓ / ✗ / ? based on served counties config |
| Source | Which search query surfaced it |

CSV export includes all columns.

---

## Current State of the Repo

- `index.html` — baseline working prototype with mock data (no live API calls yet). Demonstrates full UI/UX: sidebar filters, results table, served county indicators, CSV export. **Still uses mock data — Serper wiring is the top to-do.**
- `CLAUDE.md` — this file
- `README.md` — setup and usage instructions
- `LICENSE` — project license
- `.gitignore` — standard web project ignores
- `docs/county-coverage.md` — notes on how the served-county list is configured (user-editable via the modal; no baked-in defaults)
- `scripts/build-zip-county.sh` — regenerates `data/zip-county.json` from the U.S. Census ZCTA-to-County relationship file (VA, MD, PA, DC, NJ only)
- `data/zip-county.json` — **NOT YET GENERATED.** Run `scripts/build-zip-county.sh` once locally to produce it. The sandbox that created this commit couldn't reach `www2.census.gov` (see "Handoff Notes" below).

---

## What Needs to Be Built Next (for Claude Code)

### 1. Generate `data/zip-county.json`

Before touching the frontend, run the build script once to produce the ZIP→county lookup the frontend will need:

```bash
./scripts/build-zip-county.sh
```

Commit the resulting `data/zip-county.json`. Expected size: a few hundred KB, ~10–15k ZCTAs across VA/MD/PA/DC/NJ. Re-run whenever the Census publishes a refreshed relationship file (infrequent — the file tracks decennial Census geography).

### 2. Wire up Serper.dev API

Replace the mock-data path in `index.html` with live Serper calls.

- **Endpoint:** `POST https://google.serper.dev/search` (general) or `POST https://google.serper.dev/events` (events-specific; prefer this where available).
- **Headers:** `X-API-KEY: <user's key>`, `Content-Type: application/json`.
- **Body:** `{"q": "<query string>", "gl": "us", "hl": "en"}`.
- **Key storage:** add an API-key input to the settings panel; persist to `localStorage` under `hiss.serperApiKey`. Never hardcode.
- **Query generation:** for each selected (county, category) pair, generate the query templates from the "Event Categories" table. Interpolate county + state name (e.g. `"home show Frederick County Maryland"`).
- **Execution:** run queries **sequentially** with a small delay (300–500 ms) between calls. Serper allows bursts but the UX should also stream results progressively.
- **Progress UI:** show `"Running query 7 of 42: home show Fairfax County Virginia…"` so the coordinator can see forward motion and kill the run if needed.
- **Result normalization:** map Serper's events-result shape to the internal row shape:
  ```
  { eventName, startDate, endDate, venue, city, state, county, zip, url, eventType, sourceQuery }
  ```

### 3. ZIP + County enrichment pipeline

Serper/Google don't always hand back a clean county. Resolution order:

1. **Regex-extract ZIP** from the address/venue string (`\b\d{5}\b`).
2. **Look up county** in `data/zip-county.json` (loaded once at startup via `fetch('data/zip-county.json')` — works from `file://` in modern browsers, but if you hit CORS, inline the JSON into the HTML at build time or require the user to serve the folder with `python3 -m http.server`).
3. **Fallback to the Census Geocoder** when no ZIP is present: `https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?address=<urlencoded>&benchmark=Public_AR_Current&vintage=Current_Current&format=json`. Free, no key, but rate-limited — cache responses in memory for the session.
4. If both fail, leave county blank and flag the row gray in the served-status indicator.

**Rejected alternative:** USPS address validation API (requires an account, rate-limited, overkill for our ZIP-centric use case).

### 4. Rate limiting & loading UX

- Sequential queries with a ~400 ms delay. Never parallel-fan.
- Per-query status chip in the UI: pending / running / done / failed.
- A "Stop" button that cancels pending queries and keeps whatever finished.
- On 429 from Serper, back off 30 s and retry once; if it fails again, surface a clear error.

### 5. Served Counties modal

- Opens from a top-right button in `index.html`.
- Lists every county in VA/MD/PA/DC/NJ grouped by state, each with a checkbox.
- Persists to `localStorage` under `hiss.servedCounties` as an array of `"STATE:County Name"` strings (example: `["MD:Frederick County", "VA:Fairfax County", "DC:District of Columbia"]`).
- **No baked-in defaults.** First-run state is an empty array — all results show gray until the coordinator configures coverage.
- **Import/Export** buttons round-trip the array as JSON so the coordinator can back it up or share it across machines/browsers.
- Changes take effect immediately — existing result rows re-evaluate their served/unserved badge without a page reload.
- See `docs/county-coverage.md` for the full spec.

### 6. Deduplication logic

Same event surfaces in multiple queries. Deduplicate with this key:

```js
function dedupeKey({ eventName, startDate, zip }) {
  const name = (eventName || '')
    .toLowerCase()
    .replace(/[^\w\s]/g, '')   // strip punctuation
    .replace(/\s+/g, ' ')       // collapse whitespace
    .trim();
  return `${name}|${startDate || ''}|${zip || ''}`;
}
```

When two rows share a key, keep the first but append the second's `sourceQuery` to a list so the coordinator can see every query that surfaced the event.

### 7. Error handling

Surface each of these as an inline banner (not an alert dialog):

- **No API key / invalid API key** — prompt to re-enter in settings.
- **Rate limit (429)** — shown with a "try again in N seconds" countdown.
- **Network offline** — detected via `navigator.onLine`, with a retry button.
- **Zero results across all queries** — friendly empty state, not an error.
- **CORS / fetch failure on `data/zip-county.json`** — tell the user to serve the folder with `python3 -m http.server 8000` and reopen at `http://localhost:8000/`.

---

## Handoff Notes (read this if you're a new session picking this up)

- The repo was bootstrapped in an Anthropic-hosted Claude Code sandbox (Claude Code on the web, research preview). That sandbox had two relevant limitations:
  - **Outbound HTTP allowlist:** `curl` to `www2.census.gov` returned `403 host_not_allowed`, so `data/zip-county.json` could not be generated there. The `scripts/build-zip-county.sh` logic was validated against a synthetic fixture but has not been run against the live Census file.
  - **Git push proxy:** the sandbox's git proxy rejected pushes with 403. All prior work up to this commit exists on `claude/review-claude-md-2RWSY` locally; the initial push out of the sandbox was performed manually by the user.
- Neither limitation applies to Claude Code CLI running on the user's own machine — that's the recommended environment for finishing the build-out.
- Before writing any frontend code in the next session, **run `scripts/build-zip-county.sh` and commit `data/zip-county.json`.** Everything downstream depends on it.

---

## Repository

- **GitHub handle:** `distantgeek`
- **Repo name:** `home-improvement-search-system`
- **Remote:** `git@github.com:distantgeek/home-improvement-search-system.git` (live)

---

## Key Constraints

- **Ease of use is paramount.** The end users are not technical. The tool must work by opening a file in a browser. No terminal, no installs, no configuration files to edit.
- **County and ZIP are non-negotiable data fields.** They drive the served/unserved filtering that is the whole point of replacing the manual workflow.
- **No per-event fees.** The entire reason for building this is to escape FestivalNet's predatory per-result pricing model. Do not introduce any API with per-event or per-result billing.
````

### `docs/county-coverage.md` (new — also `mkdir -p docs` first)

````markdown
# Served County Coverage

The set of counties the company services changes over time, so HISS treats this list as user-editable configuration rather than baked-in data.

## Where it lives

- Configured at runtime via the **Served Counties** modal in `index.html`.
- Persisted to `localStorage` under the key `hiss.servedCounties` as an array of `"STATE:County Name"` entries (e.g. `"MD:Frederick County"`).
- No defaults are shipped. A fresh install starts with an empty list, and all events are flagged gray ("not configured") until the coordinator checks counties off.

## Changing the list

1. Open `index.html`.
2. Click **Served Counties** in the top-right settings area.
3. Tick or untick counties. Changes save immediately to localStorage.
4. Close the modal. Existing results re-evaluate their served/unserved badges on the fly.

## Exporting / sharing

The modal has **Export** and **Import** buttons that round-trip the served list as JSON, so the coordinator can back it up or share it across browsers/machines without a server.

## localStorage schema (for implementers)

- **Key:** `hiss.servedCounties`
- **Value:** JSON-stringified array of `"STATE:County Name"` strings. Example:
  ```json
  ["MD:Frederick County","MD:Carroll County","VA:Fairfax County","DC:District of Columbia"]
  ```
- **State codes:** `VA`, `MD`, `PA`, `DC`, `NJ` (matching the `state` field in `data/zip-county.json`).
- **County name format:** exact string from the Census relationship file's `NAMELSAD_COUNTY_20` column (e.g. `"Frederick County"`, not `"Frederick"`). DC is stored as `"DC:District of Columbia"`.
- **Empty / missing key:** treat as an empty array. Never seed defaults.

## Import / Export JSON shape

The modal's Export button serializes to a small wrapper for forward compatibility:

```json
{
  "version": 1,
  "exportedAt": "2026-04-24T12:34:56Z",
  "servedCounties": [
    "MD:Frederick County",
    "VA:Fairfax County"
  ]
}
```

The Import button accepts either the wrapped shape above or a bare array.

## Event-to-county match algorithm

When enriching a Serper result into a table row, the frontend decides the served/unserved badge as follows:

1. Resolve the event's `(state, county)` via ZIP lookup in `data/zip-county.json`.
2. Build the lookup key `"<state>:<county>"`.
3. Compare against the in-memory `Set` loaded from `hiss.servedCounties`:
   - **Green (✓)** — key is in the set.
   - **Red (✗)** — event county is known but not in the set.
   - **Gray (?)** — event county could not be resolved (no ZIP, or ZIP not in the lookup, or Census Geocoder fallback failed).

## Behavior notes

- The full county master list for VA, MD, PA, DC, and NJ is pre-loaded in `index.html`. The coordinator only chooses which of those to mark as served.
- Changes in the modal take effect immediately — existing result rows re-evaluate their served/unserved badge without a page reload. Implement this by keeping the served set in a reactive variable and re-rendering on change.
- ZIP → county resolution uses `data/zip-county.json` (generated from the U.S. Census ZCTA-to-County relationship file; see `scripts/build-zip-county.sh`).
````

### `scripts/build-zip-county.sh` (new — also `mkdir -p scripts`, then `chmod +x` after writing)

````bash
#!/usr/bin/env bash
#
# build-zip-county.sh — regenerate data/zip-county.json from the
# U.S. Census Bureau's 2020 ZCTA-to-County relationship file.
#
# Source: https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
# Filtered to VA, MD, PA, DC, NJ (state FIPS 51, 24, 42, 11, 34).
# When a ZCTA spans multiple counties, the county with the largest
# land-area overlap is chosen as the primary.
#
# Usage: scripts/build-zip-county.sh
# Requires: bash, curl, awk, python3.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
OUT="$DATA_DIR/zip-county.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
RAW="$TMP/rel.txt"

mkdir -p "$DATA_DIR"

echo "Downloading ZCTA-to-County relationship file..."
curl -fsSL "$URL" -o "$RAW"

echo "Filtering to VA, MD, PA, DC, NJ and selecting primary county per ZCTA..."
# File is pipe-delimited. Relevant columns (1-indexed):
#   2 = GEOID_ZCTA5_20     5-digit ZIP
#   4 = GEOID_COUNTY_20    5-digit county FIPS (first 2 = state FIPS)
#   5 = NAMELSAD_COUNTY_20 e.g. "Frederick County"
#   8 = AREALAND_PART      land-area overlap in m^2
awk -F'|' '
  NR == 1 { next }
  {
    state = substr($4, 1, 2)
    if (state != "51" && state != "24" && state != "42" && state != "11" && state != "34") next
    zip = $2; county = $5; area = $8 + 0
    if (!(zip in best_area) || area > best_area[zip]) {
      best_area[zip] = area
      best_state[zip] = state
      best_county[zip] = county
    }
  }
  END {
    for (k in best_state) printf "%s\t%s\t%s\n", k, best_state[k], best_county[k]
  }
' "$RAW" | sort > "$TMP/filtered.tsv"

ROWS=$(wc -l < "$TMP/filtered.tsv")
echo "Kept $ROWS unique ZCTAs across the 5 target states/jurisdictions."

echo "Emitting JSON..."
python3 - "$TMP/filtered.tsv" "$OUT" <<'PY'
import json, sys
inp, outp = sys.argv[1], sys.argv[2]
fips_state = {"51":"VA","24":"MD","42":"PA","11":"DC","34":"NJ"}
data = {}
with open(inp) as f:
    for line in f:
        zip_, fips, county = line.rstrip("\n").split("\t")
        data[zip_] = {"state": fips_state[fips], "county": county}
with open(outp, "w") as f:
    json.dump(data, f, separators=(",", ":"), sort_keys=True)
    f.write("\n")
print(f"Wrote {len(data)} entries to {outp}")
PY

echo "Done: $OUT"
````

## Commit, push, then generate the ZIP data

```bash
chmod +x scripts/build-zip-county.sh

git add .gitignore README.md CLAUDE.md docs/county-coverage.md scripts/build-zip-county.sh
git commit -m "Add README, gitignore, docs, ZIP->county script; expand CLAUDE.md handoff spec"
git push -u origin claude/review-claude-md-2RWSY

# Now generate the ZIP lookup for real (couldn't run in the web sandbox):
./scripts/build-zip-county.sh
git add data/zip-county.json
git commit -m "Generate ZIP->county lookup from Census 2020 ZCTA relationship file"
git push
```

## Sanity checks

- `git log --oneline -6` should show your two new commits on top of `ddc09ff Baseline HTML plus CLAUDE Code handoff.`
- `data/zip-county.json` should be ~several hundred KB with 10–15k entries covering VA/MD/PA/DC/NJ.
- Opening `index.html` in a browser should still show the mock-data prototype (this handoff doesn't touch frontend behavior).

## What to work on after the push lands

`CLAUDE.md` "What Needs to Be Built Next" is the ordered TODO list — start with item 2 (wire up Serper.dev) since item 1 was just completed.
````

---

That's the full thing. Paste it as your first prompt to a local Claude Code CLI session inside any empty directory (or, if you prefer, clone the repo first and paste it once you're `cd`ed in). Claude will work through the bootstrap block, create the files, commit, push, then run the build script.