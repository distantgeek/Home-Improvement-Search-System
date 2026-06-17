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
# city-county.json covers only the supported states (VA, MD, PA, DC, NJ,
# DE, MO, IL, OH, KS, WV) since city lookup is only useful for enriching events
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

echo "Collecting all ZCTA→county overlaps (all US states)..."
# County file is pipe-delimited, 18 columns (0-indexed shown):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP
#   [9]  = GEOID_COUNTY_20    5-digit county FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_COUNTY_20 e.g. "Frederick County"
#   [16] = AREALAND_PART      land-area overlap in m^2
# All overlaps are emitted; Python selects the best match per ZIP.
awk -F'|' '
  NR == 1 { next }
  {
    state = substr($10, 1, 2)
    zip = $2; county = $11; area = $17 + 0
    if (zip == "" || county == "" || state == "") next
    printf "%s\t%s\t%s\t%d\n", zip, state, county, area
  }
' "$RAW_COUNTY" | sort >"$TMP/all_county.tsv"

ROWS=$(wc -l <"$TMP/all_county.tsv")
echo "Collected $ROWS ZCTA→county overlap rows (national)."

echo "Emitting ZIP→county JSON (all US states)..."
python3 - "$TMP/all_county.tsv" "$OUT_ZIP" "$DATA_DIR/counties.json" <<'PY'
import json, re, sys
from collections import defaultdict

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

# Per-state set of canonical names for O(1) exact-match test.
canonical_sets: dict[str, set[str]] = {
    state: set(names) for state, names in counties_by_state.items()
}

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

# Collect all overlaps per ZIP: {zip: [(state_fips, census_county, area), ...]}
overlaps: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
skipped = 0
with open(inp) as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        zip_, state_fips, county, area = parts[0], parts[1], parts[2], int(parts[3])
        state = fips_state.get(state_fips)
        if state is None:
            skipped += 1
            continue
        overlaps[zip_].append((state, county, area))

# For each ZIP, prefer the overlap whose normalized name is an exact canonical
# match in counties.json (most-specific entity wins). Fall back to max area.
data = {}
for zip_, candidates in overlaps.items():
    # All candidates for a ZIP share the same state (ZCTAs don't cross state lines).
    state = candidates[0][0]
    canonical_hit = None
    canonical_area = -1
    max_area_entry = max(candidates, key=lambda x: x[2])

    for st, census_county, area in candidates:
        normed = normalize_county(census_county, st)
        if normed in canonical_sets.get(st, set()) and area > canonical_area:
            canonical_hit = (st, normed, area)
            canonical_area = area

    if canonical_hit:
        data[zip_] = {"state": canonical_hit[0], "county": canonical_hit[1]}
    else:
        st, census_county, _ = max_area_entry
        data[zip_] = {"state": st, "county": normalize_county(census_county, st)}

with open(outp, "w") as f:
    json.dump(data, f, separators=(",", ":"), sort_keys=True)
    f.write("\n")
print(f"Wrote {len(data)} ZIP entries to {outp}" + (f" (skipped {skipped} territory ZCTAs)" if skipped else ""))
PY

echo "Building city→county mapping from ZCTA-to-Place (supported states)..."
# Place file columns (0-indexed after split on |):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP (empty if no ZCTA overlap)
#   [9]  = GEOID_PLACE_20     place FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_PLACE_20  e.g. "Frederick city"
#   [16] = AREALAND_PART
# Join with zip-county.json on ZCTA (already canonical-resolved), then aggregate
# by place+state → county with highest total area overlap.
python3 - "$RAW_PLACE" "$OUT_ZIP" "$OUT_CITY" "$DATA_DIR/counties.json" <<'PY'
import json, sys, re
from collections import defaultdict

place_file, zip_county_file, outp, counties_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

target_states = {"VA","MD","PA","DC","NJ","DE","MO","IL","OH","KS","WV"}

with open(counties_path) as f:
    counties_by_state = json.load(f)["COUNTIES"]

# Load already-canonical-resolved ZIP→county for target states only.
zip_county = {}
with open(zip_county_file) as f:
    for zip_, entry in json.load(f).items():
        if entry["state"] in target_states:
            zip_county[zip_] = (entry["state"], entry["county"])

# Per-state set for O(1) independent-city lookup: "Fairfax City" → True.
city_entities: dict[str, set[str]] = {
    state: {c for c in names if re.search(r'\bCity\b', c)}
    for state, names in counties_by_state.items()
}

# Parse place file, join with county, aggregate by (state, place) → county counts.
# Independent cities (e.g. "Staunton city") are mapped directly to their canonical
# city entity rather than to the surrounding county derived from the ZIP overlap.
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

        state_abbr, _ = zip_county[zip_]
        clean = re.sub(r'\s+(city|borough|town|village|township|CDP|municipality)\s*$', '', place_name, flags=re.IGNORECASE).strip()
        if not clean:
            continue

        try:
            area = int(area_str) if area_str else 0
        except ValueError:
            area = 0

        # If "clean City" is a canonical independent-city entity, use it directly.
        city_candidate = f"{clean} City"
        if city_candidate in city_entities.get(state_abbr, set()):
            county = city_candidate
        else:
            _, county = zip_county[zip_]

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

echo "Validating county names against zip-county.json and city-county.json..."
python3 - "$DATA_DIR/counties.json" "$OUT_ZIP" "$OUT_CITY" <<'PY'
import json, sys
from collections import defaultdict

counties_file, zip_file, city_file = sys.argv[1], sys.argv[2], sys.argv[3]

with open(counties_file) as f:
    counties = json.load(f)["COUNTIES"]

covered = defaultdict(set)
with open(zip_file) as f:
    for entry in json.load(f).values():
        covered[entry["state"]].add(entry["county"])
with open(city_file) as f:
    for key, entry in json.load(f).items():
        state = key.split(":")[0]
        covered[state].add(entry["county"])

warnings = 0
for state, names in counties.items():
    for name in names:
        if name not in covered.get(state, set()):
            print(f"  WARNING: '{name}' ({state}) not in zip-county or city-county")
            warnings += 1

if warnings:
    print(f"  {warnings} county name(s) uncovered — review counties.json")
else:
    print("  All county names validated")
PY

echo "Done: $OUT_ZIP, $OUT_CITY, $DATA_DIR/counties.json"
