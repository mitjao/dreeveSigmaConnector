#!/bin/sh
set -e

# On first `run`, if no token is stored yet but credentials are present, log in
# so the container is self-bootstrapping.
if [ "$1" = "run" ] && [ ! -f "${TOKEN_DIR:-/tokens}/token.json" ] \
   && [ -n "${SIGMA_EMAIL}" ] && [ -n "${SIGMA_PASSWORD}${SIGMA_PASSWORD_FILE}" ]; then
    echo "No stored token; logging in first…"
    python -m dreeve_sigma_connector login || true
fi

exec python -m dreeve_sigma_connector "$@"
