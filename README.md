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

```yaml
  sigma-connector:
    image: ghcr.io/mitjao/dreevesigmaconnector:latest
    container_name: dreeve-sigma-connector
    restart: unless-stopped
    environment:
      SIGMA_EMAIL: you@example.com
      SIGMA_PASSWORD: your-sigma-cloud-password
      MAX_DOWNLOADS_PER_CYCLE: "50"   # gentle first backfill; 0 = all at once
      POLL_INTERVAL: "3600"
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
docker compose up -d sigma-connector            # syncs now, then every POLL_INTERVAL
docker compose logs -f sigma-connector
docker compose exec sigma-connector python -m dreeve_sigma_connector status
```

> The GHCR package inherits the repo's visibility. While the repo is **private**,
> the host pulling the image must be logged in to ghcr
> (`echo $TOKEN | docker login ghcr.io -u mitjao --password-stdin`, token with
> `read:packages`). To skip that, make the package public once under the repo's
> **Packages → package settings → Change visibility**.

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
export SIGMA_EMAIL=you@example.com SIGMA_PASSWORD='…'
export WATCH_DIR=./watch STATE_DIR=./sigma/state TOKEN_DIR=./sigma/tokens

python -m dreeve_sigma_connector login
python -m dreeve_sigma_connector sync-once --dry-run   # preview, downloads nothing
python -m dreeve_sigma_connector sync-once             # one real cycle
python -m dreeve_sigma_connector run                   # loop every POLL_INTERVAL
python -m dreeve_sigma_connector status
```

## Commands

| Command | What it does |
|---|---|
| `login` | Runs the OAuth flow once and stores the access token in `TOKEN_DIR`. |
| `sync-once` | One cycle: list activities → download new/changed → convert → write TCX. |
| `sync-once --dry-run` | Lists what *would* be delivered; downloads nothing. |
| `run` | Loops `sync-once` every `POLL_INTERVAL` seconds. Auto-relogins if the token is rejected. |
| `status` | Prints the last cycle's JSON status. |

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SIGMA_EMAIL` | — | **Required.** Your SIGMA Cloud email. |
| `SIGMA_PASSWORD` | — | **Required.** Also `SIGMA_PASSWORD_FILE` for Docker secrets. |
| `SIGMA_CLIENT_ID` / `_SECRET` | macOS DATA CENTER client | Override only if SIGMA rotates them (`tools/extract_client_creds.py`). |
| `SINCE_DAYS` | `0` | On first run, only deliver activities newer than N days (`0` = all). |
| `POLL_INTERVAL` | `3600` | Seconds between cycles in `run`. |
| `MAX_DOWNLOADS_PER_CYCLE` | `50` (compose) / `0` (unset) | Per-cycle download cap; the rest becomes `backlog` for the next cycle. |
| `DOWNLOAD_DELAY_SECONDS` | `0.5` | Pause between downloads. |
| `ON_CONFLICT` | `skip` | `skip` or `overwrite` when the `.tcx` already sits in `watch/`. |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error`. |

Delivered activities are recorded in `STATE_DIR/ledger.json` (keyed by GUID +
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
  out of your own DATA CENTER install (only needed if the baked-in defaults stop working).
- `tools/sigma_probe.py` — standalone diagnostic that logs in and dumps a raw
  `/sync` response and one activity file. Handy if SIGMA changes the API.

## Caveats

- Undocumented API: expect occasional breakage if SIGMA changes it. The probe
  tool and the decompiled reference make it fixable.
- Everything runs on your machine; your data isn't sent to any third party.
