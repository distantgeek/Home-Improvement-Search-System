#!/bin/sh
# Sourced by the official nginx entrypoint before envsubst runs on templates.
# Reads the Meilisearch key from the Docker secret file and exports it so that
# the subsequent envsubst step can substitute ${MEILI_KEY} in nginx.conf.template.
set -e

SECRET_FILE=/run/secrets/meili_key

if [ ! -f "$SECRET_FILE" ]; then
    echo "ERROR: Docker secret 'meili_key' not found at $SECRET_FILE" >&2
    exit 1
fi

MEILI_KEY=$(tr -d '[:space:]' < "$SECRET_FILE")
if [ -z "$MEILI_KEY" ]; then
    echo "ERROR: Docker secret 'meili_key' is empty" >&2
    exit 1
fi

export MEILI_KEY
echo "Loaded MEILI_KEY from Docker secret"
