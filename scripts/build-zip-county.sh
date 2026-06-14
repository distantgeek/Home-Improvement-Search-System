#!/usr/bin/env bash
#
# build-zip-county.sh — regenerate data/zip-county.json and data/city-county.json
# from the U.S. Census Bureau's 2020 ZCTA relationship files.
#
# Sources:
#   ZCTA-to-County: https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
#   ZCTA-to-Place:  https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
#
# zip-county.json covers ALL US states so the enricher can correct the state
# on any ZIP, even those outside the service area (state filter drops them).
# city-county.json covers only the 10 supported states (VA, MD, PA, DC, NJ,
# DE, MO, IL, OH, KS) since city lookup is only useful for enriching events
# that will actually appear in the index.
#
# When a ZCTA spans multiple counties/places, the one with the largest
# land-area overlap is chosen as the primary.
#
# Outputs:
#   data/zip-county.json   — ZIP → {state, county}  (all US states)
#   data/city-county.json  — "STATE:City" → {county, zctaCount}  (10 target states)
#
# Usage: scripts/build-zip-county.sh
# Requires: bash, curl, awk, python3.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
OUT_ZIP="$DATA_DIR/zip-county.json"
OUT_CITY="$DATA_DIR/city-county.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL_COUNTY="https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
URL_PLACE="https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_place20_natl.txt"
RAW_COUNTY="$TMP/county.txt"
RAW_PLACE="$TMP/place.txt"

mkdir -p "$DATA_DIR"

echo "Downloading ZCTA-to-County relationship file..."
curl -fsSL "$URL_COUNTY" -o "$RAW_COUNTY"

echo "Downloading ZCTA-to-Place relationship file..."
curl -fsSL "$URL_PLACE" -o "$RAW_PLACE"

echo "Selecting primary county per ZCTA (all US states)..."
# County file is pipe-delimited, 18 columns (0-indexed shown):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP
#   [9]  = GEOID_COUNTY_20    5-digit county FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_COUNTY_20 e.g. "Frederick County"
#   [16] = AREALAND_PART      land-area overlap in m^2
awk -F'|' '
  NR == 1 { next }
  {
    state = substr($10, 1, 2)
    zip = $2; county = $11; area = $17 + 0
    if (zip == "" || county == "" || state == "") next
    if (!(zip in best_area) || area > best_area[zip]) {
      best_area[zip] = area
      best_state[zip] = state
      best_county[zip] = county
    }
  }
  END {
    for (k in best_state) printf "%s\t%s\t%s\n", k, best_state[k], best_county[k]
  }
' "$RAW_COUNTY" | sort >"$TMP/all_county.tsv"

ROWS=$(wc -l <"$TMP/all_county.tsv")
echo "Kept $ROWS unique ZCTAs (national)."

echo "Emitting ZIP→county JSON (all US states)..."
python3 - "$TMP/all_county.tsv" "$OUT_ZIP" "$DATA_DIR/counties.json" <<'PY'
import json, re, sys

inp, outp, counties_path = sys.argv[1], sys.argv[2], sys.argv[3]

# All 50 states + DC. Territories (PR=72, VI=78, etc.) are excluded —
# they don't appear in the event pipeline's target geography.
fips_state = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT",
    "10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL",
    "18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD",
    "25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE",
    "32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND",
    "39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV",
    "55":"WI","56":"WY",
}

with open(counties_path) as f:
    counties_by_state = json.load(f)["COUNTIES"]

def normalize_county(census_name: str, state: str) -> str:
    """Map a Census county name to the canonical name in counties.json.

    For target states, counties.json uses bare names ('Frederick') or
    'X City' for independent cities. For non-target states the Census
    name is returned as-is (those events are filtered out before display).
    """
    canonical = {c.lower(): c for c in counties_by_state.get(state, [])}
    lower = census_name.lower()

    if lower in canonical:
        return canonical[lower]

    stripped = re.sub(r'\s+(county|city|borough|township|parish|district)\s*$', '', lower, flags=re.IGNORECASE).strip()
    if stripped in canonical:
        return canonical[stripped]

    if " " in stripped:
        nospace = stripped.replace(" ", "")
        if nospace in canonical:
            return canonical[nospace]

    return census_name

data = {}
skipped = 0
with open(inp) as f:
    for line in f:
        zip_, fips, county = line.rstrip("\n").split("\t")
        state = fips_state.get(fips)
        if state is None:
            skipped += 1
            continue
        data[zip_] = {"state": state, "county": normalize_county(county, state)}

with open(outp, "w") as f:
    json.dump(data, f, separators=(",", ":"), sort_keys=True)
    f.write("\n")
print(f"Wrote {len(data)} ZIP entries to {outp}" + (f" (skipped {skipped} territory ZCTAs)" if skipped else ""))
PY

echo "Building city→county mapping from ZCTA-to-Place (10 target states)..."
# Place file columns (0-indexed after split on |):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP (empty if no ZCTA overlap)
#   [9]  = GEOID_PLACE_20     place FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_PLACE_20  e.g. "Frederick city"
#   [16] = AREALAND_PART
# Join with county data on ZCTA, then aggregate by place+state → most common county.
# Intentionally limited to the 10 supported states — city lookup is only used to
# enrich events that will appear in the index; zip-county.json handles state
# correction for out-of-area ZIPs at the ZIP lookup tier.
python3 - "$RAW_PLACE" "$TMP/all_county.tsv" "$OUT_CITY" "$DATA_DIR/counties.json" <<'PY'
import json, sys, re
from collections import defaultdict

place_file, county_file, outp, counties_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

target_fips = {"51","24","42","11","34","10","29","17","39","20"}
fips_state = {"51":"VA","24":"MD","42":"PA","11":"DC","34":"NJ","10":"DE","29":"MO","17":"IL","39":"OH","20":"KS"}
target_states = target_fips

with open(counties_path) as f:
    counties_by_state = json.load(f)["COUNTIES"]

def normalize_county(census_name: str, state: str) -> str:
    canonical = {c.lower(): c for c in counties_by_state.get(state, [])}
    lower = census_name.lower()
    if lower in canonical:
        return canonical[lower]
    stripped = re.sub(r'\s+(county|city|borough|township|parish|district)\s*$', '', lower, flags=re.IGNORECASE).strip()
    if stripped in canonical:
        return canonical[stripped]
    if " " in stripped:
        nospace = stripped.replace(" ", "")
        if nospace in canonical:
            return canonical[nospace]
    return census_name

# Load ZIP→county mapping for target states only (all_county.tsv is national
# but city lookup is only needed for the 10 supported states).
zip_county = {}
with open(county_file) as f:
    for line in f:
        zip_, fips, county = line.rstrip("\n").split("\t")
        if fips not in target_fips:
            continue
        state = fips_state[fips]
        zip_county[zip_] = (state, normalize_county(county, state))

# Parse place file, join with county, aggregate by (state, place) → county counts
place_counts = defaultdict(lambda: defaultdict(int))
with open(place_file, encoding="utf-8") as f:
    header = f.readline()
    for line in f:
        parts = line.split("|")
        if len(parts) < 17:
            continue
        zip_ = parts[1].strip()
        place_fips = parts[9].strip()
        place_name = parts[10].strip()
        area_str = parts[16].strip()

        if not zip_ or not place_fips:
            continue
        if zip_ not in zip_county:
            continue

        state_fips = place_fips[:2]
        if state_fips not in target_states:
            continue

        state_abbr, county = zip_county[zip_]
        clean = re.sub(r'\s+(city|borough|town|village|township|CDP|municipality)\s*$', '', place_name, flags=re.IGNORECASE).strip()
        if not clean:
            continue

        try:
            area = int(area_str) if area_str else 0
        except ValueError:
            area = 0

        key = f"{state_abbr}:{clean}"
        place_counts[key][county] += area

result = {}
for key, county_areas in place_counts.items():
    best_county = max(county_areas, key=county_areas.get)
    total_zctas = len(county_areas)
    result[key] = {"county": best_county, "zctaCount": total_zctas}

with open(outp, "w") as f:
    json.dump(result, f, separators=(",", ":"), sort_keys=True)
    f.write("\n")
print(f"Wrote {len(result)} city entries to {outp}")
PY

echo "Validating county names in zip-county.json against counties.json..."
python3 - "$DATA_DIR/counties.json" "$OUT_ZIP" <<'PY'
import json, sys
from collections import defaultdict

counties_file, zip_file = sys.argv[1], sys.argv[2]

with open(counties_file) as f:
    counties = json.load(f)["COUNTIES"]

with open(zip_file) as f:
    zip_county = json.load(f)

census_counties = defaultdict(set)
for entry in zip_county.values():
    census_counties[entry["state"]].add(entry["county"])

warnings = 0
for state, names in counties.items():
    for name in names:
        if name not in census_counties.get(state, set()):
            print(f"  WARNING: '{name}' ({state}) not found in normalized Census ZIP data")
            warnings += 1

if warnings:
    print(f"  {warnings} county name(s) without Census ZIP match — review counties.json")
else:
    print("  All county names validated — exact match with Census data")
PY

echo "Done: $OUT_ZIP, $OUT_CITY, $DATA_DIR/counties.json"
