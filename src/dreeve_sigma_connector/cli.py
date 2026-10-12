"""
Command-line interface for the SIGMA -> Dreeve connector.

  login       run the OAuth flow once and store the access token
  sync-once   one cycle: list -> download -> convert -> write to watch/
  sync-once --dry-run   show what would be delivered, download nothing
  run         sync-once now (unless SIGMA_CONNECTOR_SYNC_ON_STARTUP=false), then
              on the SIGMA_CONNECTOR_SCHEDULE cron schedule
  status      print the last cycle's status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from . import auth
from .client import InvalidTokenError, SigmaCloudClient
from .config import Config
from .connector import Connector
from .cron import CronSchedule


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _get_client(cfg: Config) -> SigmaCloudClient:
    tok = auth.load_token(cfg.token_dir)
    if not tok:
        print("No stored token. Run `login` first.", file=sys.stderr)
        sys.exit(2)
    return SigmaCloudClient(tok["access_token"])


def cmd_login(cfg: Config, args) -> int:
    tok = auth.login(cfg.email, cfg.password, cfg.client_id, cfg.client_secret)
    auth.save_token(cfg.token_dir, tok)
    print(f"Logged in. Token stored in {auth.token_path(cfg.token_dir)} "
          f"(scope={tok.get('scope')}).")
    return 0


def _ensure_token(cfg: Config) -> SigmaCloudClient:
    """Client from stored token; auto-login if we have credentials and none stored."""
    tok = auth.load_token(cfg.token_dir)
    if tok:
        return SigmaCloudClient(tok["access_token"])
    if cfg.email and cfg.password:
        tok = auth.login(cfg.email, cfg.password, cfg.client_id, cfg.client_secret)
        auth.save_token(cfg.token_dir, tok)
        return SigmaCloudClient(tok["access_token"])
    print("No stored token and no SIGMA_CONNECTOR_EMAIL/SIGMA_CONNECTOR_PASSWORD "
          "to log in with.", file=sys.stderr)
    sys.exit(2)


def cmd_sync_once(cfg: Config, args) -> int:
    client = _ensure_token(cfg)
    conn = Connector(cfg, client)
    try:
        res = conn.run_once(dry_run=args.dry_run)
    except InvalidTokenError:
        # token died — try one re-login if we can, then retry once
        if not (cfg.email and cfg.password):
            print("Token rejected and no credentials to re-login. Run `login`.",
                  file=sys.stderr)
            return 3
        logging.getLogger("sigma.cli").info("token rejected; re-logging in")
        tok = auth.login(cfg.email, cfg.password, cfg.client_id, cfg.client_secret)
        auth.save_token(cfg.token_dir, tok)
        conn = Connector(cfg, SigmaCloudClient(tok["access_token"]))
        res = conn.run_once(dry_run=args.dry_run)
    print(json.dumps(res.as_dict(), indent=2))
    return 0


def cmd_run(cfg: Config, args) -> int:
    log = logging.getLogger("sigma.cli")
    schedule = CronSchedule(cfg.schedule)  # fail fast on a bad expression
    first = True
    while True:
        if cfg.sync_on_startup or not first:
            try:
                cmd_sync_once(cfg, args)
            except Exception as e:  # keep the loop alive across transient errors
                log.error("cycle error: %s", e)
        first = False
        nxt = schedule.next_after(datetime.now())
        log.info("next cycle at %s (schedule %r)", nxt.isoformat(sep=" "), cfg.schedule)
        # sleep in chunks so wall-clock jumps (suspend, NTP, DST) don't skew the wake-up
        while (remaining := nxt.timestamp() - time.time()) > 0:
            time.sleep(min(remaining, 300))


def cmd_status(cfg: Config, args) -> int:
    p = os.path.join(cfg.state_dir, "status.json")
    if not os.path.exists(p):
        print("{}")
        return 0
    with open(p) as f:
        print(f.read())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dreeve-sigma-connector")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="run the OAuth flow and store the token")
    p_once = sub.add_parser("sync-once", help="run a single sync cycle")
    p_once.add_argument("--dry-run", action="store_true",
                        help="list what would be delivered without downloading")
    p_run = sub.add_parser("run", help="sync now, then on the SIGMA_CONNECTOR_SCHEDULE cron schedule")
    p_run.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="print the last cycle status")

    args = parser.parse_args(argv)
    cfg = Config.from_env()
    _setup_logging(cfg.log_level)

    return {
        "login": cmd_login,
        "sync-once": cmd_sync_once,
        "run": cmd_run,
        "status": cmd_status,
    }[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
