#!/usr/bin/env bash
# pip-audit — Python dependency vulnerability scanner (CVE audit)
# OWASP reference: A06 Vulnerable and Outdated Components
# NIST reference: SI-2 (flaw remediation), CM-8 (component inventory)
# pip-audit doc: https://github.com/pypa/pip-audit
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Running pip-audit on pipeline/requirements*.txt ..."

pip-audit -r pipeline/requirements.txt -r pipeline/requirements-dev.txt "$@"

echo ""
echo "pip-audit: complete."
