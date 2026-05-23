#!/usr/bin/env bash
# ESLint — coding standards + OWASP security rules on index.html
# OWASP reference: eslint-plugin-security, eslint-plugin-no-unsanitized
# NIST reference: SI-10 (input validation), CM-7 (least functionality)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
echo "Running ESLint (OWASP A03/XSS rules) on index.html..."
npx eslint index.html --format stylish "$@"
