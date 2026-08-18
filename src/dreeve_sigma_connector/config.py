"""Configuration for the SIGMA → Dreeve connector, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

BASE_URL = "https://www.sigma-data-cloud.com"
REDIRECT_URI = "https://www.sigma-dc-control.com"  # registered redirect_uri of the DATA CENTER client


def _read(name: str, default: str = "") -> str:
    """Env var, or its *_FILE indirection (for Docker secrets)."""
    v = os.environ.get(name)
    if v:
        return v
    fp = os.environ.get(name + "_FILE")
    if fp and os.path.exists(fp):
        with open(fp) as f:
            return f.read().strip()
    return default


@dataclass
class Config:
    email: str
    password: str
    client_id: str
    client_secret: str
    watch_dir: str
    state_dir: str
    token_dir: str
    since_days: int          # only deliver activities newer than N days on first run (0 = all)
    poll_interval: int       # seconds between cycles in `run`
    max_per_cycle: int       # cap downloads per cycle (0 = no cap)
    download_delay: float    # pause between downloads (seconds)
    on_conflict: str         # skip | overwrite when the .tcx already exists in watch/
    output_format: str       # tcx (only tcx implemented)
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            email=_read("SIGMA_CONNECTOR_EMAIL"),
            password=_read("SIGMA_CONNECTOR_PASSWORD"),
            # The OAuth client_id/secret of an official SIGMA app. Not shipped
            # with the connector — extract them from your own SIGMA DATA CENTER
            # install once (see README → "Getting the client credentials" and
            # tools/extract_client_creds.py).
            client_id=_read("SIGMA_CONNECTOR_CLIENT_ID"),
            client_secret=_read("SIGMA_CONNECTOR_CLIENT_SECRET"),
            watch_dir=_read("SIGMA_CONNECTOR_WATCH_DIR", "/watch"),
            state_dir=_read("SIGMA_CONNECTOR_STATE_DIR", "/state"),
            token_dir=_read("SIGMA_CONNECTOR_TOKEN_DIR", "/tokens"),
            since_days=int(_read("SIGMA_CONNECTOR_SINCE_DAYS", "0") or "0"),
            poll_interval=int(_read("SIGMA_CONNECTOR_POLL_INTERVAL", "3600") or "3600"),
            max_per_cycle=int(_read("SIGMA_CONNECTOR_MAX_DOWNLOADS_PER_CYCLE", "0") or "0"),
            download_delay=float(_read("SIGMA_CONNECTOR_DOWNLOAD_DELAY_SECONDS", "0.5") or "0.5"),
            on_conflict=_read("SIGMA_CONNECTOR_ON_CONFLICT", "skip"),
            output_format=_read("SIGMA_CONNECTOR_OUTPUT_FORMAT", "tcx"),
            log_level=_read("SIGMA_CONNECTOR_LOG_LEVEL", "info"),
        )
