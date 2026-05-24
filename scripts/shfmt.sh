#!/usr/bin/env bash
# shfmt — shell script formatting (mvdan/sh)
# OWASP reference: A08 Software and Data Integrity Failures (formatting standard)
# NIST reference: SA-11 (developer testing and evaluation)
# shfmt doc: https://github.com/mvdan/sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

case "${1:-check}" in
  check)
    echo "Checking shell script formatting (shfmt)..."
    shfmt -d -i 2 -ci -bn scripts/*.sh
    EXIT=$?
    if [[ $EXIT -ne 0 ]]; then
      echo ""
      echo "Formatting issues found — run 'sh scripts/shfmt.sh fix' to apply."
      exit $EXIT
    fi
    echo "All scripts formatted correctly."
    ;;
  fix)
    echo "Applying shfmt formatting to scripts/*.sh ..."
    shfmt -w -i 2 -ci -bn scripts/*.sh
    echo "Done."
    ;;
esac
