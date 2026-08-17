"""Configuration for the SIGMA → Dreeve connector, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

BASE_URL = "https://www.sigma-data-cloud.com"
REDIRECT_URI = "https://www.sigma-dc-control.com"  # registered redirect_uri of the DATA CENTER client

# OAuth client credentials embedded in the official SIGMA apps. Defaults are the
# macOS DATA CENTER client (extracted from CloudWorker.swf). Override via env if
# SIGMA ever rotates them; see tools/extract_client_creds.py.
DEFAULT_CLIENT_ID = "de3d306c44114f565065687d534d6efa"
DEFAULT_CLIENT_SECRET = "d145ca897ed15ade3feffad9d545e4ef"


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
            email=_read("SIGMA_EMAIL"),
            password=_read("SIGMA_PASSWORD"),
            client_id=_read("SIGMA_CLIENT_ID", DEFAULT_CLIENT_ID),
            client_secret=_read("SIGMA_CLIENT_SECRET", DEFAULT_CLIENT_SECRET),
            watch_dir=_read("WATCH_DIR", "/watch"),
            state_dir=_read("STATE_DIR", "/state"),
            token_dir=_read("TOKEN_DIR", "/tokens"),
            since_days=int(_read("SINCE_DAYS", "0") or "0"),
            poll_interval=int(_read("POLL_INTERVAL", "3600") or "3600"),
            max_per_cycle=int(_read("MAX_DOWNLOADS_PER_CYCLE", "0") or "0"),
            download_delay=float(_read("DOWNLOAD_DELAY_SECONDS", "0.5") or "0.5"),
            on_conflict=_read("ON_CONFLICT", "skip"),
            output_format=_read("OUTPUT_FORMAT", "tcx"),
            log_level=_read("LOG_LEVEL", "info"),
        )
