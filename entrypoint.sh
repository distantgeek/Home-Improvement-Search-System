#!/bin/sh
set -e

HTDOCS=/usr/local/apache2/htdocs/index.html

if [ -z "${MEILI_URL:-}" ]; then
  echo "ERROR: MEILI_URL environment variable is required" >&2
  exit 1
fi
if [ -z "${MEILI_KEY:-}" ]; then
  echo "ERROR: MEILI_KEY environment variable is required" >&2
  exit 1
fi

sed -i \
  -e "s|__MEILI_URL__|${MEILI_URL}|g" \
  -e "s|__MEILI_KEY__|${MEILI_KEY}|g" \
  "$HTDOCS"

exec "$@"
