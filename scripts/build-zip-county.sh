#!/usr/bin/env bash
#
# build-zip-county.sh — regenerate data/zip-county.json and data/city-county.json
# from the U.S. Census Bureau's 2020 ZCTA relationship files.
#
# Sources:
#   ZCTA-to-County: https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
#   ZCTA-to-Place:  https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
# Filtered to VA, MD, PA, DC, NJ, DE (state FIPS 51, 24, 42, 11, 34, 10).
# When a ZCTA spans multiple counties/places, the one with the largest
# land-area overlap is chosen as the primary.
#
# Outputs:
#   data/zip-county.json   — ZIP → {state, county}
#   data/city-county.json  — "STATE:City" → {county, zctaCount}
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

echo "Filtering to VA, MD, PA, DC, NJ, DE and selecting primary county per ZCTA..."
# County file is pipe-delimited, 18 columns (0-indexed shown):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP
#   [9]  = GEOID_COUNTY_20    5-digit county FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_COUNTY_20 e.g. "Frederick County"
#   [16] = AREALAND_PART      land-area overlap in m^2
awk -F'|' '
  NR == 1 { next }
  {
    state = substr($10, 1, 2)
    if (state != "51" && state != "24" && state != "42" && state != "11" && state != "34" && state != "10") next
    zip = $2; county = $11; area = $17 + 0
    if (zip == "" || county == "") next
    if (!(zip in best_area) || area > best_area[zip]) {
      best_area[zip] = area
      best_state[zip] = state
      best_county[zip] = county
    }
  }
  END {
    for (k in best_state) printf "%s\t%s\t%s\n", k, best_state[k], best_county[k]
  }
' "$RAW_COUNTY" | sort > "$TMP/filtered_county.tsv"

ROWS=$(wc -l < "$TMP/filtered_county.tsv")
echo "Kept $ROWS unique ZCTAs across the 6 target states/jurisdictions."

echo "Emitting ZIP→county JSON..."
python3 - "$TMP/filtered_county.tsv" "$OUT_ZIP" <<'PY'
import json, sys
inp, outp = sys.argv[1], sys.argv[2]
fips_state = {"51":"VA","24":"MD","42":"PA","11":"DC","34":"NJ","10":"DE"}
data = {}
with open(inp) as f:
    for line in f:
        zip_, fips, county = line.rstrip("\n").split("\t")
        data[zip_] = {"state": fips_state[fips], "county": county}
with open(outp, "w") as f:
    json.dump(data, f, separators=(",", ":"), sort_keys=True)
    f.write("\n")
print(f"Wrote {len(data)} ZIP entries to {outp}")
PY

echo "Building city→county mapping from ZCTA-to-Place..."
# Place file columns (0-indexed after split on |):
#   [1]  = GEOID_ZCTA5_20     5-digit ZIP (empty if no ZCTA overlap)
#   [9]  = GEOID_PLACE_20     place FIPS (first 2 = state FIPS)
#   [10] = NAMELSAD_PLACE_20  e.g. "Frederick city"
#   [16] = AREALAND_PART
# Join with county data on ZCTA, then aggregate by place+state → most common county
python3 - "$RAW_PLACE" "$TMP/filtered_county.tsv" "$OUT_CITY" <<'PY'
import json, sys, re
from collections import defaultdict

place_file, county_file, outp = sys.argv[1], sys.argv[2], sys.argv[3]

fips_state = {"51":"VA","24":"MD","42":"PA","11":"DC","34":"NJ","10":"DE"}
target_states = set(fips_state.keys())

# Load ZIP→county mapping
zip_county = {}
with open(county_file) as f:
    for line in f:
        zip_, fips, county = line.rstrip("\n").split("\t")
        zip_county[zip_] = (fips_state[fips], county)

# Parse place file, join with county, aggregate by (state, place) → county counts
place_counts = defaultdict(lambda: defaultdict(int))
with open(place_file, encoding="utf-8") as f:
    header = f.readline()  # skip header
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
        # Clean place name: strip suffixes like " city", " borough", " CDP", " town", " village"
        clean = re.sub(r'\s+(city|borough|town|village|township|CDP|municipality)\s*$', '', place_name, flags=re.IGNORECASE).strip()
        if not clean:
            continue

        try:
            area = int(area_str) if area_str else 0
        except ValueError:
            area = 0

        key = f"{state_abbr}:{clean}"
        place_counts[key][county] += area

# For each city, pick the county with the largest total area overlap
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

echo "Done: $OUT_ZIP and $OUT_CITY"
