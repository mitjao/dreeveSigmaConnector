#!/bin/sh
set -e

# On first `run`, if no token is stored yet but credentials are present, log in
# so the container is self-bootstrapping.
if [ "$1" = "run" ] && [ ! -f "${SIGMA_CONNECTOR_TOKEN_DIR:-/tokens}/token.json" ] \
   && [ -n "${SIGMA_CONNECTOR_EMAIL}" ] \
   && [ -n "${SIGMA_CONNECTOR_PASSWORD}${SIGMA_CONNECTOR_PASSWORD_FILE}" ]; then
    echo "No stored token; logging in first…"
    python -m dreeve_sigma_connector login || true
fi

exec python -m dreeve_sigma_connector "$@"
