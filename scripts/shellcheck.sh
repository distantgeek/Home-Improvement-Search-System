#!/usr/bin/env bash
# ShellCheck — shell script static analysis
# OWASP reference: A06 Vulnerable and Outdated Components, A08 Software and Data Integrity Failures
# NIST reference: SA-11 (developer testing and evaluation)
# ShellCheck doc: https://www.shellcheck.net/wiki/
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Running ShellCheck on scripts/*.sh ..."

EXIT_CODE=0
for script in scripts/*.sh; do
  echo "  ${script}"
  if ! shellcheck -x "$script"; then
    EXIT_CODE=1
  fi
done

if [[ $EXIT_CODE -ne 0 ]]; then
  echo ""
  echo "ShellCheck: issues found — review above."
  exit 1
fi

echo ""
echo "ShellCheck: all scripts pass."
