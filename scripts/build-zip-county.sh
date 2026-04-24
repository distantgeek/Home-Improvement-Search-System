#!/usr/bin/env bash
#
# build-zip-county.sh — regenerate data/zip-county.json from the
# U.S. Census Bureau's 2020 ZCTA-to-County relationship file.
#
# Source: https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/
# Filtered to VA, MD, PA, DC, NJ, DE (state FIPS 51, 24, 42, 11, 34, 10).
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

echo "Filtering to VA, MD, PA, DC, NJ, DE and selecting primary county per ZCTA..."
# File is pipe-delimited. Relevant columns (1-indexed):
#   2 = GEOID_ZCTA5_20     5-digit ZIP
#   4 = GEOID_COUNTY_20    5-digit county FIPS (first 2 = state FIPS)
#   5 = NAMELSAD_COUNTY_20 e.g. "Frederick County"
#   8 = AREALAND_PART      land-area overlap in m^2
awk -F'|' '
  NR == 1 { next }
  {
    state = substr($4, 1, 2)
    if (state != "51" && state != "24" && state != "42" && state != "11" && state != "34" && state != "10") next
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
echo "Kept $ROWS unique ZCTAs across the 6 target states/jurisdictions."

echo "Emitting JSON..."
python3 - "$TMP/filtered.tsv" "$OUT" <<'PY'
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
print(f"Wrote {len(data)} entries to {outp}")
PY

echo "Done: $OUT"
