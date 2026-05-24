#!/usr/bin/env bash
# Run Playwright E2E tests inside the existing playwright container.
# Uses podman on atomic Fedora — no system package installs needed.
#
# Usage:
#   ./scripts/test-container.sh              # run all tests
#   ./scripts/test-container.sh --grep smoke # run a subset
#   npm test                                 # same as above via package.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="mcr.microsoft.com/playwright:v1.60.0-noble"
PORT=8000

# Start Python HTTP server from repo root (serves index.html and data/)
python3 -m http.server "$PORT" --directory "$REPO_ROOT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

# Wait for the server to be ready (retry up to 10 times, counter unused in body)
# shellcheck disable=SC2034
for i in $(seq 1 10); do
  curl -sf "http://localhost:$PORT/" -o /dev/null && break
  sleep 0.3
done

# Run tests inside the playwright container.
# --network host: container reaches localhost:PORT (the Python server above)
# --rm: clean up container after run
# :z on volume mount: SELinux relabeling for Fedora atomic
podman run --rm \
  --network host \
  -v "${REPO_ROOT}:/app:z" \
  -w /app \
  "$IMAGE" \
  npx playwright test "$@"
