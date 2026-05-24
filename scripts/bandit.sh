#!/usr/bin/env bash
# Bandit — Python security linter (OWASP Top 10 for Python)
# OWASP reference: A04 Insecure Design, A05 Security Misconfiguration
# NIST reference: SI-10 (input validation), SA-11 (developer testing)
# Bandit doc: https://bandit.readthedocs.io/en/latest/blacklists/
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Running Bandit (Python SAST) on pipeline/**/*.py ..."

bandit \
  -r pipeline/ \
  -x pipeline/tests/ \
  --format screen \
  "$@"

echo ""
echo "Bandit: complete."
