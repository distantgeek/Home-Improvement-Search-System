#!/usr/bin/env bash
# Retire.js — detect vulnerable JS library versions referenced in index.html
# OWASP reference: A06 Vulnerable and Outdated Components
# NIST reference: SI-2 (flaw remediation), CM-8 (component inventory)
# CVE note: retire@5 depends on uuid@9 (GHSA-w5hq-g745-h8pq, moderate).
#   uuid is used only for CycloneDX report serial numbers via v4() — NOT the
#   vulnerable v3/v5/v6+buf path. Risk accepted: dev-only tool, not exploitable.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo "Running Retire.js (OWASP A06: Vulnerable Components) on index.html..."
npx retire --path . --outputformat text --exitwith 13 2>&1 || {
  EXIT=$?
  if [[ $EXIT -eq 13 ]]; then
    echo "Retire.js: vulnerable libraries found (exit 13) — review output above"
    exit 1
  fi
}
