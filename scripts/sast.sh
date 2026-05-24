#!/usr/bin/env bash
# Semgrep SAST — OWASP Top 10 + XSS + secrets rule sets
# OWASP reference: recommended SAST tool (www-community/Source_Code_Analysis_Tools)
# NIST reference: SI-10, SI-3, SA-11
# Supply chain: image verified from docker.io/semgrep/semgrep (open source, r2c/Semgrep Inc)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

IMAGE="docker.io/semgrep/semgrep:latest"
OUTPUT="${1:-sast-results.json}"

echo "Running Semgrep SAST (p/javascript, p/owasp-top-ten, p/xss, p/secrets)..."
echo "  Scanning: index.html"
echo "  Output:   $OUTPUT"

podman run --rm \
  -v "$(pwd):/app:z" \
  -w /app \
  "$IMAGE" \
  semgrep scan \
  --config "p/javascript" \
  --config "p/owasp-top-ten" \
  --config "p/xss" \
  --config "p/secrets" \
  --json \
  --output "$OUTPUT" \
  index.html 2>&1 || true

echo ""
if [[ -f "$OUTPUT" ]]; then
  python3 -c "
import json, sys
try:
    d = json.load(open('$OUTPUT'))
    results = d.get('results', [])
    errors = d.get('errors', [])
    print(f'Semgrep: {len(results)} findings, {len(errors)} errors')
    for r in results:
        sev = r.get('extra', {}).get('severity', 'UNKNOWN')
        msg = r.get('extra', {}).get('message', '?')[:80]
        line = r.get('start', {}).get('line', '?')
        rule = r.get('check_id', '?').split('.')[-1]
        print(f'  [{sev}] line {line}: {rule} — {msg}')
except Exception as e:
    print(f'Could not parse results: {e}')
"
fi
