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
- Eventbrite API considered as a supplemental source (free, official, good home show coverage) — stretch goal

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

- `index.html` — baseline working prototype with mock data (no live API calls yet). Demonstrates full UI/UX: sidebar filters, results table, served county indicators, CSV export.
- `CLAUDE.md` — this file
- `README.md` — setup and usage instructions
- `.gitignore` — standard web project ignores
- `docs/county-coverage.md` — placeholder for the served counties list once provided

---

## What Needs to Be Built Next (for Claude Code)

1. **Wire up Serper.dev API** — replace mock data with live calls. API key input in UI → stored in localStorage. Build the multi-query execution logic with deduplication.
2. **County/ZIP enrichment** — Google Events results don't always include county. Need a lookup or inference layer (ZIP → County mapping, or Google Maps Geocoding API as a fallback).
3. **Rate limiting / loading UX** — show query-by-query progress as searches run (Serper has rate limits; queries should run sequentially with delay).
4. **Served Counties modal** — full configuration UI for checking which counties the company operates in, persisted to localStorage.
5. **Deduplication logic** — same event may appear across multiple query results. Deduplicate on normalized event name + date + ZIP.
6. **Error handling** — bad API key, rate limit exceeded, no results, network offline.
7. **(Stretch) Eventbrite supplemental source** — free official API, good home show coverage, would complement Serper results.

---

## Repository

- **GitHub handle:** `distantgeek`
- **Repo name:** `home-improvement-search-system`
- **Remote:** `git@github.com:distantgeek/home-improvement-search-system.git` (to be created)

---

## Key Constraints

- **Ease of use is paramount.** The end users are not technical. The tool must work by opening a file in a browser. No terminal, no installs, no configuration files to edit.
- **County and ZIP are non-negotiable data fields.** They drive the served/unserved filtering that is the whole point of replacing the manual workflow.
- **No per-event fees.** The entire reason for building this is to escape FestivalNet's predatory per-result pricing model. Do not introduce any API with per-event or per-result billing.
