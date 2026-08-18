# Dreeve ⇽ SIGMA Cloud connector

Automatically pulls **all your trainings out of SIGMA Cloud**, converts each to a
**TCX** file and drops it into **[Dreeve](https://dreeve.app)**'s `watch/` folder —
exactly like the official Garmin / Polar / Wahoo connectors, so Dreeve imports
them with no manual exporting.

```
SIGMA Cloud → connector → ./watch/ → Dreeve imports it
```

Stdlib-only Python (no pip dependencies). Runs as a Docker container or directly.

A prebuilt multi-arch image (amd64 + arm64) is published to the GitHub Container
Registry on every push to `main`:

```
ghcr.io/mitjao/dreevesigmaconnector:latest
```

## Add it to your Dreeve `docker-compose.yml`

Drop this service next to your Dreeve `app` / `daemon`, mounting the **same**
`./watch` folder they use — no local build needed:

All of the connector's env vars are prefixed **`SIGMA_CONNECTOR_`** so they never
collide with Dreeve's own variables when they share a compose/env file.

```yaml
  sigma-connector:
    image: ghcr.io/mitjao/dreevesigmaconnector:latest
    container_name: dreeve-sigma-connector
    restart: unless-stopped
    environment:
      SIGMA_CONNECTOR_EMAIL: you@example.com
      SIGMA_CONNECTOR_PASSWORD: your-sigma-cloud-password
      # See "Getting the client credentials" below.
      SIGMA_CONNECTOR_CLIENT_ID: your-client-id
      SIGMA_CONNECTOR_CLIENT_SECRET: your-client-secret
      SIGMA_CONNECTOR_MAX_DOWNLOADS_PER_CYCLE: "50"   # gentle first backfill; 0 = all at once
      SIGMA_CONNECTOR_POLL_INTERVAL: "3600"
    volumes:
      - ./watch:/watch                # the SAME folder Dreeve imports from
      - ./sigma/state:/state
      - ./sigma/tokens:/tokens
    command: ["run"]
```

Then:

```bash
docker compose pull sigma-connector
docker compose run --rm sigma-connector login   # one-time: stores an access token
docker compose up -d sigma-connector            # syncs now, then every cycle
docker compose logs -f sigma-connector
docker compose exec sigma-connector python -m dreeve_sigma_connector status
```

> The GHCR package inherits the repo's visibility. While the repo is **private**,
> the host pulling the image must be logged in to ghcr
> (`echo $TOKEN | docker login ghcr.io -u mitjao --password-stdin`, token with
> `read:packages`). To skip that, make the package public once under the repo's
> **Packages → package settings → Change visibility**.

## Getting the client credentials

SIGMA Cloud has no public API, so the connector authenticates with the same
OAuth `client_id` / `client_secret` the official **SIGMA DATA CENTER** desktop app
uses — the same unofficial-API basis the Garmin/Polar Dreeve connectors rely on.
These are **not** shipped with the connector; you extract them once from your own
DATA CENTER install. They rarely change, so this is a one-time step.

1. **Get DATA CENTER** — install it, or just download the macOS installer and
   pull the one file out of it (no install needed):

   ```bash
   # macOS installer (any recent version works):
   curl -LO https://sigma-download1.com/DataCenter-mac-apple-5.9.2.dmg
   hdiutil attach -nobrowse DataCenter-mac-apple-5.9.2.dmg
   cp "/Volumes/SIGMA DataCenter/SIGMA DataCenter.app/Contents/Resources/CloudWorker.swf" .
   hdiutil detach "/Volumes/SIGMA DataCenter"
   ```

   On Windows the file lives at
   `…\SIGMA DATA CENTER\resources\CloudWorker.swf` inside the install dir.

2. **Extract the values** with the bundled tool (Python 3, stdlib only):

   ```bash
   python3 tools/extract_client_creds.py CloudWorker.swf
   # or point it at an installed app bundle / directory
   ```

   It prints the strings around each `CLIENT_ID_*` / `CLIENT_SECRET_*` constant.
   Take the **MAC** pair — `client_id` is the short value next to `CLIENT_ID_MAC`,
   `client_secret` the one next to `CLIENT_SECRET_MAC`. (Use `CLIENT_ID_WINDOWS` /
   `CLIENT_SECRET_WINDOWS` if you extracted from the Windows build — either pair
   works.) If a block looks ambiguous, the value is the string directly after the
   label, minus the leading number.

3. **Set them** as `SIGMA_CONNECTOR_CLIENT_ID` / `SIGMA_CONNECTOR_CLIENT_SECRET`
   (env, compose `environment:`, or `.env`).

If SIGMA ever rotates these, the connector starts failing at `login`; re-run the
extractor against the current DATA CENTER version to get fresh values.

## Quick start (this checkout)

Using the bundled `docker-compose.yml` (copy `.env.example` to `.env` first):

```bash
docker compose run --rm sigma-connector login
docker compose up -d
docker compose logs -f sigma-connector
```

## Quick start (no Docker)

```bash
export PYTHONPATH=src
export SIGMA_CONNECTOR_EMAIL=you@example.com SIGMA_CONNECTOR_PASSWORD='…'
export SIGMA_CONNECTOR_CLIENT_ID='…' SIGMA_CONNECTOR_CLIENT_SECRET='…'
export SIGMA_CONNECTOR_WATCH_DIR=./watch \
       SIGMA_CONNECTOR_STATE_DIR=./sigma/state \
       SIGMA_CONNECTOR_TOKEN_DIR=./sigma/tokens

python -m dreeve_sigma_connector login
python -m dreeve_sigma_connector sync-once --dry-run   # preview, downloads nothing
python -m dreeve_sigma_connector sync-once             # one real cycle
python -m dreeve_sigma_connector run                   # loop every cycle
python -m dreeve_sigma_connector status
```

## Commands

| Command | What it does |
|---|---|
| `login` | Runs the OAuth flow once and stores the access token in the token dir. |
| `sync-once` | One cycle: list activities → download new/changed → convert → write TCX. |
| `sync-once --dry-run` | Lists what *would* be delivered; downloads nothing. |
| `run` | Loops `sync-once` every `SIGMA_CONNECTOR_POLL_INTERVAL` seconds. Auto-relogins if the token is rejected. |
| `status` | Prints the last cycle's JSON status. |

## Configuration

All variables are prefixed `SIGMA_CONNECTOR_`. Secret values also accept a
`…_FILE` variant (e.g. `SIGMA_CONNECTOR_PASSWORD_FILE`) for Docker secrets.

| Variable | Default | Meaning |
|---|---|---|
| `SIGMA_CONNECTOR_EMAIL` | — | **Required.** Your SIGMA Cloud email. |
| `SIGMA_CONNECTOR_PASSWORD` | — | **Required.** Your SIGMA Cloud password. |
| `SIGMA_CONNECTOR_CLIENT_ID` | — | **Required.** OAuth client id — see [Getting the client credentials](#getting-the-client-credentials). |
| `SIGMA_CONNECTOR_CLIENT_SECRET` | — | **Required.** Matching OAuth client secret. |
| `SIGMA_CONNECTOR_SINCE_DAYS` | `0` | On first run, only deliver activities newer than N days (`0` = all). |
| `SIGMA_CONNECTOR_POLL_INTERVAL` | `3600` | Seconds between cycles in `run`. |
| `SIGMA_CONNECTOR_MAX_DOWNLOADS_PER_CYCLE` | `0` (unset) / `50` (example) | Per-cycle download cap; the rest becomes `backlog` for the next cycle. |
| `SIGMA_CONNECTOR_DOWNLOAD_DELAY_SECONDS` | `0.5` | Pause between downloads. |
| `SIGMA_CONNECTOR_ON_CONFLICT` | `skip` | `skip` or `overwrite` when the `.tcx` already sits in `watch/`. |
| `SIGMA_CONNECTOR_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error`. |
| `SIGMA_CONNECTOR_WATCH_DIR` | `/watch` | Where TCX files are written (Dreeve's watch folder). |
| `SIGMA_CONNECTOR_STATE_DIR` | `/state` | Ledger + status file location. |
| `SIGMA_CONNECTOR_TOKEN_DIR` | `/tokens` | Stored access token location. |

Delivered activities are recorded in `<state dir>/ledger.json` (keyed by GUID +
modificationDate), so re-runs don't re-deliver, an edited activity *is* refreshed,
and a capped backfill resumes where it left off. Files are written as
`sigma-<GUID>.tcx`; Dreeve's own duplicate detection is the final backstop.

## How it works

SIGMA Cloud has **no public API**. This connector talks to the same private
endpoints the official SIGMA DATA CENTER desktop app uses (the same unofficial-API
basis the Garmin/Polar Dreeve connectors rely on), against **your own** account.
It was reverse-engineered from DATA CENTER's `CloudWorker.swf`.

| Concern | Detail |
|---|---|
| Base URL | `https://www.sigma-data-cloud.com` |
| Auth | OAuth2 **authorization-code** flow: `/oauth/authorize` → form login at `/login.do` → consent → `/oauth/token`. Redirect URI `https://www.sigma-dc-control.com`. The issued token is effectively non-expiring; the `refresh_token` grant is not allowed, so we re-login only if a token is rejected. |
| List | `POST /sync?access_token=…`, body `{"dataList":{"type":"ACTIVITY","lastSync":0,"list":[]}}` → `{"dataLists":[{"dataList":[{GUID, modificationDate, activityDate, status, url}]}]}`. |
| Download | Each `url` is a pre-signed S3 link to a **ZIP** containing one **`.slf`** (SIGMA Log Format, XML). Fetched with no extra auth header. |
| Convert | `.slf` → **TCX** (`src/dreeve_sigma_connector/{slf,tcx}.py`). GPS, altitude, distance, speed, heart rate, cadence and power are carried across, and **laps** are rebuilt from the SLF `fitStandardLap` markers (split by cumulative distance, or by time for GPS-less indoor rides). Unit scales (altitude = mm, times = centiseconds) and lap boundaries were confirmed against DATA CENTER's own FIT-export mapper. |

Some cloud entries (e.g. manually-entered summaries) have no file; they're
reported as `without_file`, not errors.

## Tools

- `tools/extract_client_creds.py` — read the app's OAuth `client_id`/`client_secret`
  out of your own DATA CENTER install (see [Getting the client credentials](#getting-the-client-credentials)).
- `tools/sigma_probe.py` — standalone diagnostic that logs in and dumps a raw
  `/sync` response and one activity file. Handy if SIGMA changes the API.

## Caveats

- Undocumented API: expect occasional breakage if SIGMA changes it. The probe
  tool and the decompiled reference make it fixable.
- Everything runs on your machine; your data isn't sent to any third party.
