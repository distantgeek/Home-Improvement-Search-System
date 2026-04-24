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
- ZIP → county resolution uses `data/zip-county.json` (generated from the U.S. Census ZCTA-to-County relationship file; see `scripts/build-zip-county.sh`).
