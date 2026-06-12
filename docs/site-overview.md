## HISS — Home Improvement Show Search

### What It Is

An event discovery tool for a home improvement company that exhibits at trade shows,
home expos, and fairs across VA, MD, PA, DC, NJ, and DE.

### Workflow

- **Pipeline runs automatically** every Sunday at 3 AM — scrapes Google Events via
  Serper.dev
- **Manual file ingest** when the coordinator exports a FestivalNet My List HTML page
  (highest priority data)
- **Data is deduplicated**, enriched with county/ZIP info, stored in SQLite, and pushed
  to Meilisearch (search index)
- **Coordinator opens a browser** — no installs, no terminal — searches by state, dates,
  and event type
- **Results show** event name, dates, venue, county, ZIP, type, attendance, and a link
- **Served-county overlay**: coordinator pre-tags which counties they serve; results are
  colour-coded green (served), red (not served), or grey (unknown)
- **CSV export** downloads visible results for use in spreadsheets

### What's in the Index

| Metric | Value |
|---|---|
| Total events | 2,571 |
| Time range | Mar 2026 – May 2027 |
| Sources | 406 FestivalNet (manual exports), 2,165 Google Events |
| Coverage | 10 states, 649 counties/locales |

### Features

- **Search** by state, date range, event type (Home Show, County Fair, etc.)
- **Filter** by county and served/not-served status
- **County coverage modal** — coordinator checks off which counties they serve; saved in
  browser
- **CSV export** — downloads exactly what's on screen
- **Full-screen table** with sortable columns
- **Data freshness** — shows event count in toolbar

### Current Limitations

| Limitation | Detail |
|---|---|
| **1,000 result cap** | Search returns max 1,000 events; if the coordinator searches all states with no date filter, 1,500+ events are invisible |
| **FestivalNet is manual** | Coordinator must export HTML from FestivalNet and run a CLI command (no web upload yet) |
| **No Eventbrite data** | Free tier returns 401; structured venue/ZIP enrichment from Eventbrite URLs is built but inactive |
| **Out-of-region noise** | A handful of non-target-state events (Portland, Columbus) occasionally appear from Google search results |
| **No dashboard alerts** | Coordinator must manually search each region; no "new events near county X" dashboard |
| **Single-user** | No accounts, permissions, or concurrent-user support (not needed for current use) |

### Deployed Stack

Four Docker containers on a home server:

| Service | Role |
|---|---|
| **hiss** | nginx web server — serves the frontend, proxies search queries |
| **hiss-meilisearch** | Search engine — handles all queries from the browser |
| **hiss-pipeline** | Python process — fetches, enriches, deduplicates, syncs data weekly |
| **hiss-datasette** | Read-only SQLite browser (internal access only) |
