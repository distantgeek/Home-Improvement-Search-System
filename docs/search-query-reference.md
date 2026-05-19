# HISS Search Query Reference

How the pipeline finds events: what gets searched, why, and what happens to the results.

---

## Why a cache?

The original `index.html` called Serper.dev directly from the browser — one API call per
query, 368 queries per full run, all triggered by the coordinator clicking Search. That's
slow (≈2.5 minutes per run), burns through the free-tier quota (2,500/month), and blocks
the UI for the entire duration.

The pipeline replaces that with a **weekly background cache**:

1. The pipeline container runs all 368 queries every Sunday at 3am.
2. Results are normalized, deduplicated, and written to SQLite (`hiss.db`).
3. From there they're indexed in Meilisearch, which the frontend will query directly
   (Phase 1 — not yet implemented).

The coordinator never waits for API calls. Results are already there.

---

## Where queries come from

Queries are built by `pipeline/fetchers/serper.py: build_all_queries()`, which calls
`build_queries_for_state()` for each of the six states/jurisdictions in order:
**MD → VA → PA → NJ → DE → DC**.

Each state generates queries from two sources:

- **State-level templates** — fixed phrases that target the state as a whole (e.g.
  `"home show Maryland 2026"`). These run once per event type per state.
- **Per-county fair queries** — one query per county/locality in that state
  (e.g. `"Frederick County fair Maryland 2026"`). Only the County Fair event type
  generates per-county queries; all other types use state-level queries only.

The current year is appended to every query so Google returns upcoming events, not
historical ones. Duplicates across states are deduplicated before the list is finalised.

---

## Query totals by state

| State | Jurisdiction | Counties/localities | Total queries |
|---|---|---|---|
| MD | Maryland | 24 | 46 |
| VA | Virginia | 120 | 142 |
| PA | Pennsylvania | 67 | 89 |
| NJ | New Jersey | 21 | 43 |
| DE | Delaware | 3 | 25 |
| DC | Washington DC | 1 | 23 |
| **Total** | | **236** | **368** |

Virginia's count is high because it has 120 independent cities and counties (Virginia
treats cities as county-equivalents). Delaware and DC are small by comparison.

---

## Event type templates

Each event type maps to a fixed set of search strings. The year (`2026` currently) is
appended to every query.

### Home Show *(5 queries per state)*
```
home show <State> <year>
home improvement expo <State> <year>
home improvement show <State> <year>
remodeling show <State> <year>
home expo <State> <year>
```

### Home & Garden *(3 queries per state)*
```
home and garden show <State> <year>
home garden expo <State> <year>
outdoor living show <State> <year>
```

### County Fair *(1 state-level + 1 per county)*
```
county fair <State> <year>
<County Name> fair <State> <year>   ← one per county/locality
```
County names that already include "City", "County", "District", "Parish", or "Borough"
are used as-is. All others get " County" appended (e.g. "Frederick" → "Frederick County").

### State Fair *(1 query per state)*
```
state fair <State> <year>
```

### Art & Craft *(3 queries per state)*
```
art fair <State> <year>
craft show <State> <year>
craft festival <State> <year>
```

### Food Festival *(3 queries per state)*
```
food festival <State> <year>
wine festival <State> <year>
seafood festival <State> <year>
```

### Fall Festival *(3 queries per state)*
```
fall festival <State> <year>
harvest festival <State> <year>
pumpkin festival <State> <year>
```

### Community Festival *(3 queries per state)*
```
community festival <State> <year>
cultural festival <State> <year>
outdoor festival <State> <year>
```

---

## All 368 queries (current run — 2026)

### Maryland (46)

```
home show Maryland 2026
home improvement expo Maryland 2026
home improvement show Maryland 2026
remodeling show Maryland 2026
home expo Maryland 2026
home and garden show Maryland 2026
home garden expo Maryland 2026
outdoor living show Maryland 2026
county fair Maryland 2026
Allegany County fair Maryland 2026
Anne Arundel County fair Maryland 2026
Baltimore City fair Maryland 2026
Baltimore County fair Maryland 2026
Calvert County fair Maryland 2026
Caroline County fair Maryland 2026
Carroll County fair Maryland 2026
Cecil County fair Maryland 2026
Charles County fair Maryland 2026
Dorchester County fair Maryland 2026
Frederick County fair Maryland 2026
Garrett County fair Maryland 2026
Harford County fair Maryland 2026
Howard County fair Maryland 2026
Kent County fair Maryland 2026
Montgomery County fair Maryland 2026
Prince George's County fair Maryland 2026
Queen Anne's County fair Maryland 2026
St. Mary's County fair Maryland 2026
Somerset County fair Maryland 2026
Talbot County fair Maryland 2026
Washington County fair Maryland 2026
Wicomico County fair Maryland 2026
Worcester County fair Maryland 2026
state fair Maryland 2026
art fair Maryland 2026
craft show Maryland 2026
craft festival Maryland 2026
food festival Maryland 2026
wine festival Maryland 2026
seafood festival Maryland 2026
fall festival Maryland 2026
harvest festival Maryland 2026
pumpkin festival Maryland 2026
community festival Maryland 2026
cultural festival Maryland 2026
outdoor festival Maryland 2026
```

### Virginia (142)

```
home show Virginia 2026
home improvement expo Virginia 2026
home improvement show Virginia 2026
remodeling show Virginia 2026
home expo Virginia 2026
home and garden show Virginia 2026
home garden expo Virginia 2026
outdoor living show Virginia 2026
county fair Virginia 2026
Accomack County fair Virginia 2026
Albemarle County fair Virginia 2026
Alexandria City fair Virginia 2026
Alleghany County fair Virginia 2026
Amelia County fair Virginia 2026
Amherst County fair Virginia 2026
Appomattox County fair Virginia 2026
Arlington County fair Virginia 2026
Augusta County fair Virginia 2026
Bath County fair Virginia 2026
Bedford County fair Virginia 2026
Bland County fair Virginia 2026
Botetourt County fair Virginia 2026
Brunswick County fair Virginia 2026
Buchanan County fair Virginia 2026
Buckingham County fair Virginia 2026
Campbell County fair Virginia 2026
Caroline County fair Virginia 2026
Carroll County fair Virginia 2026
Charles City fair Virginia 2026
Charlotte County fair Virginia 2026
Charlottesville City fair Virginia 2026
Chesterfield County fair Virginia 2026
Clarke County fair Virginia 2026
Culpeper County fair Virginia 2026
Cumberland County fair Virginia 2026
Dickenson County fair Virginia 2026
Dinwiddie County fair Virginia 2026
Essex County fair Virginia 2026
Fairfax County fair Virginia 2026
Fairfax City fair Virginia 2026
Falls Church City fair Virginia 2026
Fauquier County fair Virginia 2026
Floyd County fair Virginia 2026
Fluvanna County fair Virginia 2026
Franklin County fair Virginia 2026
Franklin City fair Virginia 2026
Frederick County fair Virginia 2026
Fredericksburg City fair Virginia 2026
Giles County fair Virginia 2026
Gloucester County fair Virginia 2026
Goochland County fair Virginia 2026
Grayson County fair Virginia 2026
Greene County fair Virginia 2026
Greensville County fair Virginia 2026
Halifax County fair Virginia 2026
Hampton City fair Virginia 2026
Hanover County fair Virginia 2026
Harrisonburg City fair Virginia 2026
Henrico County fair Virginia 2026
Henry County fair Virginia 2026
Highland County fair Virginia 2026
Isle of Wight County fair Virginia 2026
James City fair Virginia 2026
King and Queen County fair Virginia 2026
King George County fair Virginia 2026
King William County fair Virginia 2026
Lancaster County fair Virginia 2026
Lee County fair Virginia 2026
Loudoun County fair Virginia 2026
Louisa County fair Virginia 2026
Lunenburg County fair Virginia 2026
Lynchburg City fair Virginia 2026
Madison County fair Virginia 2026
Manassas City fair Virginia 2026
Manassas Park City fair Virginia 2026
Mathews County fair Virginia 2026
Mecklenburg County fair Virginia 2026
Middlesex County fair Virginia 2026
Montgomery County fair Virginia 2026
Nelson County fair Virginia 2026
New Kent County fair Virginia 2026
Newport News City fair Virginia 2026
Norfolk City fair Virginia 2026
Northampton County fair Virginia 2026
Northumberland County fair Virginia 2026
Nottoway County fair Virginia 2026
Orange County fair Virginia 2026
Page County fair Virginia 2026
Patrick County fair Virginia 2026
Petersburg City fair Virginia 2026
Pittsylvania County fair Virginia 2026
Poquoson City fair Virginia 2026
Portsmouth City fair Virginia 2026
Powhatan County fair Virginia 2026
Prince Edward County fair Virginia 2026
Prince George County fair Virginia 2026
Prince William County fair Virginia 2026
Pulaski County fair Virginia 2026
Radford City fair Virginia 2026
Rappahannock County fair Virginia 2026
Richmond City fair Virginia 2026
Richmond County fair Virginia 2026
Roanoke City fair Virginia 2026
Roanoke County fair Virginia 2026
Rockbridge County fair Virginia 2026
Rockingham County fair Virginia 2026
Russell County fair Virginia 2026
Salem City fair Virginia 2026
Scott County fair Virginia 2026
Shenandoah County fair Virginia 2026
Smyth County fair Virginia 2026
Southampton County fair Virginia 2026
Spotsylvania County fair Virginia 2026
Stafford County fair Virginia 2026
Staunton City fair Virginia 2026
Suffolk City fair Virginia 2026
Surry County fair Virginia 2026
Sussex County fair Virginia 2026
Tazewell County fair Virginia 2026
Virginia Beach City fair Virginia 2026
Warren County fair Virginia 2026
Washington County fair Virginia 2026
Waynesboro City fair Virginia 2026
Westmoreland County fair Virginia 2026
Williamsburg City fair Virginia 2026
Winchester City fair Virginia 2026
Wise County fair Virginia 2026
Wythe County fair Virginia 2026
York County fair Virginia 2026
state fair Virginia 2026
art fair Virginia 2026
craft show Virginia 2026
craft festival Virginia 2026
food festival Virginia 2026
wine festival Virginia 2026
seafood festival Virginia 2026
fall festival Virginia 2026
harvest festival Virginia 2026
pumpkin festival Virginia 2026
community festival Virginia 2026
cultural festival Virginia 2026
outdoor festival Virginia 2026
```

### Pennsylvania (89)

```
home show Pennsylvania 2026
home improvement expo Pennsylvania 2026
home improvement show Pennsylvania 2026
remodeling show Pennsylvania 2026
home expo Pennsylvania 2026
home and garden show Pennsylvania 2026
home garden expo Pennsylvania 2026
outdoor living show Pennsylvania 2026
county fair Pennsylvania 2026
Adams County fair Pennsylvania 2026
Allegheny County fair Pennsylvania 2026
Armstrong County fair Pennsylvania 2026
Beaver County fair Pennsylvania 2026
Bedford County fair Pennsylvania 2026
Berks County fair Pennsylvania 2026
Blair County fair Pennsylvania 2026
Bradford County fair Pennsylvania 2026
Bucks County fair Pennsylvania 2026
Butler County fair Pennsylvania 2026
Cambria County fair Pennsylvania 2026
Cameron County fair Pennsylvania 2026
Carbon County fair Pennsylvania 2026
Centre County fair Pennsylvania 2026
Chester County fair Pennsylvania 2026
Clarion County fair Pennsylvania 2026
Clearfield County fair Pennsylvania 2026
Clinton County fair Pennsylvania 2026
Columbia County fair Pennsylvania 2026
Crawford County fair Pennsylvania 2026
Cumberland County fair Pennsylvania 2026
Dauphin County fair Pennsylvania 2026
Delaware County fair Pennsylvania 2026
Elk County fair Pennsylvania 2026
Erie County fair Pennsylvania 2026
Fayette County fair Pennsylvania 2026
Forest County fair Pennsylvania 2026
Franklin County fair Pennsylvania 2026
Fulton County fair Pennsylvania 2026
Greene County fair Pennsylvania 2026
Huntingdon County fair Pennsylvania 2026
Indiana County fair Pennsylvania 2026
Jefferson County fair Pennsylvania 2026
Juniata County fair Pennsylvania 2026
Lackawanna County fair Pennsylvania 2026
Lancaster County fair Pennsylvania 2026
Lawrence County fair Pennsylvania 2026
Lebanon County fair Pennsylvania 2026
Lehigh County fair Pennsylvania 2026
Luzerne County fair Pennsylvania 2026
Lycoming County fair Pennsylvania 2026
McKean County fair Pennsylvania 2026
Mercer County fair Pennsylvania 2026
Mifflin County fair Pennsylvania 2026
Monroe County fair Pennsylvania 2026
Montgomery County fair Pennsylvania 2026
Montour County fair Pennsylvania 2026
Northampton County fair Pennsylvania 2026
Northumberland County fair Pennsylvania 2026
Perry County fair Pennsylvania 2026
Philadelphia County fair Pennsylvania 2026
Pike County fair Pennsylvania 2026
Potter County fair Pennsylvania 2026
Schuylkill County fair Pennsylvania 2026
Snyder County fair Pennsylvania 2026
Somerset County fair Pennsylvania 2026
Sullivan County fair Pennsylvania 2026
Susquehanna County fair Pennsylvania 2026
Tioga County fair Pennsylvania 2026
Union County fair Pennsylvania 2026
Venango County fair Pennsylvania 2026
Warren County fair Pennsylvania 2026
Washington County fair Pennsylvania 2026
Wayne County fair Pennsylvania 2026
Westmoreland County fair Pennsylvania 2026
Wyoming County fair Pennsylvania 2026
York County fair Pennsylvania 2026
state fair Pennsylvania 2026
art fair Pennsylvania 2026
craft show Pennsylvania 2026
craft festival Pennsylvania 2026
food festival Pennsylvania 2026
wine festival Pennsylvania 2026
seafood festival Pennsylvania 2026
fall festival Pennsylvania 2026
harvest festival Pennsylvania 2026
pumpkin festival Pennsylvania 2026
community festival Pennsylvania 2026
cultural festival Pennsylvania 2026
outdoor festival Pennsylvania 2026
```

### New Jersey (43)

```
home show New Jersey 2026
home improvement expo New Jersey 2026
home improvement show New Jersey 2026
remodeling show New Jersey 2026
home expo New Jersey 2026
home and garden show New Jersey 2026
home garden expo New Jersey 2026
outdoor living show New Jersey 2026
county fair New Jersey 2026
Atlantic County fair New Jersey 2026
Bergen County fair New Jersey 2026
Burlington County fair New Jersey 2026
Camden County fair New Jersey 2026
Cape May County fair New Jersey 2026
Cumberland County fair New Jersey 2026
Essex County fair New Jersey 2026
Gloucester County fair New Jersey 2026
Hudson County fair New Jersey 2026
Hunterdon County fair New Jersey 2026
Mercer County fair New Jersey 2026
Middlesex County fair New Jersey 2026
Monmouth County fair New Jersey 2026
Morris County fair New Jersey 2026
Ocean County fair New Jersey 2026
Passaic County fair New Jersey 2026
Salem County fair New Jersey 2026
Somerset County fair New Jersey 2026
Sussex County fair New Jersey 2026
Union County fair New Jersey 2026
Warren County fair New Jersey 2026
state fair New Jersey 2026
art fair New Jersey 2026
craft show New Jersey 2026
craft festival New Jersey 2026
food festival New Jersey 2026
wine festival New Jersey 2026
seafood festival New Jersey 2026
fall festival New Jersey 2026
harvest festival New Jersey 2026
pumpkin festival New Jersey 2026
community festival New Jersey 2026
cultural festival New Jersey 2026
outdoor festival New Jersey 2026
```

### Delaware (25)

```
home show Delaware 2026
home improvement expo Delaware 2026
home improvement show Delaware 2026
remodeling show Delaware 2026
home expo Delaware 2026
home and garden show Delaware 2026
home garden expo Delaware 2026
outdoor living show Delaware 2026
county fair Delaware 2026
Kent County fair Delaware 2026
New Castle County fair Delaware 2026
Sussex County fair Delaware 2026
state fair Delaware 2026
art fair Delaware 2026
craft show Delaware 2026
craft festival Delaware 2026
food festival Delaware 2026
wine festival Delaware 2026
seafood festival Delaware 2026
fall festival Delaware 2026
harvest festival Delaware 2026
pumpkin festival Delaware 2026
community festival Delaware 2026
cultural festival Delaware 2026
outdoor festival Delaware 2026
```

### Washington DC (23)

```
home show Washington DC 2026
home improvement expo Washington DC 2026
home improvement show Washington DC 2026
remodeling show Washington DC 2026
home expo Washington DC 2026
home and garden show Washington DC 2026
home garden expo Washington DC 2026
outdoor living show Washington DC 2026
county fair Washington DC 2026
District of Columbia fair Washington DC 2026
state fair Washington DC 2026
art fair Washington DC 2026
craft show Washington DC 2026
craft festival Washington DC 2026
food festival Washington DC 2026
wine festival Washington DC 2026
seafood festival Washington DC 2026
fall festival Washington DC 2026
harvest festival Washington DC 2026
pumpkin festival Washington DC 2026
community festival Washington DC 2026
cultural festival Washington DC 2026
outdoor festival Washington DC 2026
```

---

## What happens to each query

Each query is sent as a `POST` to `https://google.serper.dev/search`:

```json
{
  "q": "home show Maryland 2026",
  "gl": "us",
  "hl": "en",
  "num": 50
}
```

`gl: "us"` locks the geography to US results. `num: 50` requests 50 results per query.
Serper passes this to Google and returns the parsed SERP.

### Two result paths

**Path 1 — Events carousel** (`eventsResults[]` or `events[]`): Google's structured
events carousel. These come back with a title, date, venue, and address already parsed.
Tagged as `source_type: "serper_events"`. This is the preferred path — structured data
means better county resolution.

**Path 2 — Organic fallback** (`organic[]`): When Google has no events carousel for a
query (common for county fair searches in rural areas), the organic web results are
filtered through `organics_to_events()`. This function looks for result titles that
contain event-signal keywords (`fair`, `show`, `expo`, `festival`, etc.), extracts
attendance figures and contact info from the snippet, and constructs an EventItem from
the title and URL. Tagged as `source_type: "serper_organic"`. Lower confidence; gets
lower priority in deduplication.

### Timing

- **400ms delay** between every query — protects against rate limits and keeps traffic
  below Serper's burst threshold.
- **HTTP 429 handling** — on a rate-limit response, the pipeline waits 30 seconds and
  retries once before logging and moving on.
- **Full run time** — 368 queries × 400ms minimum = ~2.5 minutes, plus network latency.
  In practice 3–5 minutes per weekly run.

---

## After the queries

Once all 368 queries return, results go through the normalisation and dedup pipeline:

```
Raw results (~2,100–2,200)
       ↓
normalize_event()     — standardise fields, extract ZIP from address string
       ↓
eb_enrich             — fetch structured address data for Eventbrite-URL events
       ↓
Enricher.enrich()     — three-tier county resolution:
                         Tier 1: ZIP → zip-county.json (~3,940 entries)
                         Tier 2: county name scan (regex over address/venue/title)
                         Tier 3: city → city-county.json (~3,822 entries)
       ↓
Date filter           — drop events with start_date before Jan 1 of current year
       ↓
exact_dedup()         — key: normalized_name|year|locality; higher-priority source wins
       ↓
fuzzy_merge_results() — Jaccard similarity ≥ 0.60 within year|county buckets;
                         loser URL moved to winner's sources[] list
       ↓
~1,000–1,050 unique events
       ↓
SQLite upsert         — every upsert resets synced=0; purge events > 30 days past end_date
       ↓
Meilisearch sync      — push synced=0 rows in batches of 100; mark synced=1 on success
```

The final Meilisearch index typically holds **950–1,050 documents** after a full run,
covering events across all six states from approximately now through the end of the
current year.

---

## Serper.dev quota

The free tier is **2,500 searches/month**. One full pipeline run costs 368 queries.
Running weekly (4–5 times/month) costs ~1,600–1,840 queries/month — well within the
free tier with room for manual re-runs.

---

## Updating the query set

All search terms are defined in two files:

- **`pipeline/constants.py`** — `COUNTIES` (the county lists per state), `EVENT_TYPES`
  (the eight event type names), `STATE_NAMES` (state code → full name for query strings)
- **`pipeline/fetchers/serper.py: build_queries_for_state()`** — the query templates per
  event type

To add a new event type: add a name to `EVENT_TYPES` in `constants.py`, then add a
matching entry to the `templates` dict in `build_queries_for_state()`. The pipeline picks
it up on the next run.

To add a new state: add it to `COUNTIES`, `STATE_ORDER`, and `STATE_NAMES` in
`constants.py`. The Eventbrite Discovery fetcher (`_STATE_CENTROIDS`) also needs a
lat/lng centroid added.
