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
   The script downloads the U.S. Census ZCTA-to-County relationship file, filters it to VA/MD/PA/DC/NJ/DE, and emits a compact JSON lookup. Requires `bash`, `curl`, `awk`, and `python3`. Runs in a few seconds on a normal connection — the fetch is the dominant cost; ~5 MB download, ~55k rows nationally, ~10–15k kept after filtering.
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

**States:** Virginia (VA), Maryland (MD), Pennsylvania (PA), Washington DC, New Jersey (NJ), Delaware (DE)

Full county lists are pre-loaded in the frontend for all 6 states/jurisdictions. DC is a single entry (District of Columbia).

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

All 7 original TODO items are complete. The app is fully functional with live Serper.dev API calls.

- `index.html` — complete app with live Serper API, fuzzy dedup, expandable alternate URLs, served counties modal, CSV export, error handling, rate limiting, and stop button
- `CLAUDE.md` — this file
- `README.md` — setup and usage instructions
- `LICENSE` — project license
- `.gitignore` — standard web project ignores
- `docs/county-coverage.md` — notes on how the served-county list is configured
- `scripts/build-zip-county.sh` — regenerates `data/zip-county.json` and `data/city-county.json` from Census ZCTA-to-County and ZCTA-to-Place files (VA, MD, PA, DC, NJ, DE)
- `data/zip-county.json` — ZIP → county lookup (~3,940 entries)
- `data/city-county.json` — city → county lookup (~3,822 entries)
- `Dockerfile` + `docker-compose.yml` — httpd:alpine container with GHCR auto-build on push to `main`

---

## Completed Features

### 1. `data/zip-county.json` — Done
Generated from Census 2020 ZCTA-to-County relationship file. Covers VA, MD, PA, DC, NJ, DE.

### 2. Serper.dev API — Done
Live `POST https://google.serper.dev/search` calls with API key from UI (localStorage: `hiss.serperApiKey`). Sequential queries with 400ms delay. Organic-to-event parsing for home shows that don't appear in Google's events carousel.

### 3. ZIP + County enrichment — Done
Three-tier county resolution pipeline:
- **Tier 1:** Regex ZIP extraction → `data/zip-county.json` lookup (~3,940 entries)
- **Tier 2:** Scan address/venue/title for known county names via compiled regex (~200 counties across 6 states)
- **Tier 3:** City name → county lookup via `data/city-county.json` (~3,822 entries, derived from Census ZCTA-to-Place joined with ZCTA-to-County)
- All tiers run sequentially; first match wins. County name regex is built at startup from the `COUNTIES` constant.

### 4. Rate limiting & loading UX — Done
Per-query progress display, stop button, 429 backoff with 30s retry, offline detection, CORS error guidance.

### 5. Served Counties modal — Done
Checkbox UI grouped by state, persisted to `hiss.servedCounties` in localStorage. Import/Export as JSON. Green/red/gray indicators with filter toggle.

### 6. Deduplication logic — Done (enhanced)
Two-tier dedup:
- **Tier 1** (during search): Exact key match on normalized name + year + locality. Smart hyphen handling to keep the event-keyword side.
- **Tier 2** (post-search): Fuzzy merge via Jaccard token similarity (60% threshold) within date+location buckets. Strips state names, filler words, venue fragments before comparing.
- Merged rows keep the best source URL as primary and accumulate alternates in `altUrls[]`. Expandable rows in the UI show alternate URLs. CSV export includes an "Alternate URLs" column.

### 7. Error handling — Done
Inline error banners for: no/invalid API key, 429 rate limit, network offline, zero results, CORS/zip-county fetch failure.

---

## Handoff Notes

- The repo was originally bootstrapped in an Anthropic-hosted Claude Code sandbox. All sandbox limitations (blocked outbound HTTP, git push proxy) have been resolved since moving to local development.
- Census data files (`zip-county.json`, `city-county.json`) have been generated from live Census files with correct column indices.
- GitHub Actions workflow uses `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` to avoid Node.js 20 deprecation warnings.
- SSH access to the TrueNAS deployment host is configured (`truenas-local` in `~/.ssh/config`, user `assistant` with key `~/.ssh/assistant_ed25519`).
- Dockge manages stacks at `/mnt/kevbot-store/stacks/` on the TrueNAS host.
- The `hiss` container runs on port 8888 on the TrueNAS host.

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
- **State codes:** `VA`, `MD`, `PA`, `DC`, `NJ`, `DE` (matching the `state` field in `data/zip-county.json`).
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

- The full county master list for VA, MD, PA, DC, NJ, and DE is pre-loaded in `index.html`. The coordinator only chooses which of those to mark as served.
- Changes in the modal take effect immediately — existing result rows re-evaluate their served/unserved badge without a page reload. Implement this by keeping the served set in a reactive variable and re-rendering on change.
- County resolution uses a three-tier pipeline: ZIP lookup (`data/zip-county.json`), county name scanning (regex built from `COUNTIES` constant), and city lookup (`data/city-county.json`). See `scripts/build-zip-county.sh` for data generation.
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

## What to work on next

All original TODO items are complete. Future work may include:
- Tuning the Jaccard similarity threshold based on real-world results
- Adding more noise words to `normalizeForDedup()` if new duplicate patterns emerge
- Improving organic-to-event parsing accuracy
- Adding more event types or search query templates
- Verifying county resolution accuracy with live search results and adjusting tier priorities if needed
````

---

That's the full thing. Paste it as your first prompt to a local Claude Code CLI session inside any empty directory (or, if you prefer, clone the repo first and paste it once you're `cd`ed in). Claude will work through the bootstrap block, create the files, commit, push, then run the build script.