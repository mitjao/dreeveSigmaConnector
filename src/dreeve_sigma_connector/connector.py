"""
The connector cycle: list SIGMA activities -> pick new/changed ones ->
download each (ZIP->SLF) -> convert to TCX -> write into Dreeve's watch folder.

Mirrors the shape of the official Dreeve Garmin/Polar connectors: a ledger for
dedup and resumable backfill, a per-cycle download cap, and a status file.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

from .client import InvalidTokenError, SigmaClientError, SigmaCloudClient
from .config import Config
from .ledger import Ledger
from .slf import parse_slf
from .tcx import activity_to_tcx

log = logging.getLogger("sigma.connector")


@dataclass
class CycleResult:
    listed: int = 0
    delivered: int = 0
    skipped: int = 0        # already current in the ledger
    failed: int = 0
    too_old: int = 0        # older than SINCE_DAYS
    without_file: int = 0   # server has no downloadable file (e.g. manual entries)
    backlog: int = 0        # still owed a download after this cycle's cap
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "listed": self.listed, "delivered": self.delivered,
            "skipped": self.skipped, "failed": self.failed,
            "too_old": self.too_old, "without_file": self.without_file,
            "backlog": self.backlog, "errors": self.errors[:10],
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


class Connector:
    def __init__(self, cfg: Config, client: SigmaCloudClient):
        self.cfg = cfg
        self.client = client
        self.ledger = Ledger(cfg.state_dir)
        os.makedirs(cfg.watch_dir, exist_ok=True)
        os.makedirs(cfg.state_dir, exist_ok=True)

    def _since_ms(self) -> int:
        if self.cfg.since_days <= 0:
            return 0
        return _now_ms() - self.cfg.since_days * 86400_000

    def run_once(self, dry_run: bool = False) -> CycleResult:
        res = CycleResult()
        since = self._since_ms()
        items = self.client.list_activities(last_sync_ms=0)
        res.listed = len(items)
        log.info("listed %d activities from SIGMA Cloud", len(items))

        # Newest first, so a capped first run grabs recent rides before old ones.
        items.sort(key=lambda it: it.get("activityDate") or 0, reverse=True)

        delivered = 0
        for it in items:
            guid = it.get("GUID") or ""
            mod = it.get("modificationDate") or 0
            adate = it.get("activityDate") or 0
            url = it.get("url")

            if since and adate and adate < since:
                res.too_old += 1
                continue
            if not self.ledger.needs_delivery(guid, mod):
                res.skipped += 1
                continue
            if not url:
                # Manual/summary entries the cloud has no file for — not an error.
                res.without_file += 1
                continue
            if self.cfg.max_per_cycle and delivered >= self.cfg.max_per_cycle:
                res.backlog += 1
                continue

            try:
                if dry_run:
                    log.info("[dry-run] would deliver %s (%s)", guid, _fmt_date(adate))
                    delivered += 1
                    res.delivered += 1
                    continue
                fname = self._deliver(guid, mod, url)
                self.ledger.mark(guid, mod, fname, _now_ms())
                delivered += 1
                res.delivered += 1
                log.info("delivered %s -> %s", guid, fname)
                if self.cfg.download_delay:
                    time.sleep(self.cfg.download_delay)
            except SigmaClientError as e:
                res.failed += 1
                res.errors.append(f"{guid}: {e}")
                log.warning("failed %s: %s", guid, e)

        if not dry_run:
            self.ledger.save()
        self._write_status(res)
        return res

    def _deliver(self, guid: str, mod, url: str) -> str:
        slf_bytes = self.client.download_slf(url)
        act = parse_slf(slf_bytes)
        act.guid = act.guid or guid
        tcx = activity_to_tcx(act)

        fname = f"sigma-{guid}.tcx"
        dest = os.path.join(self.cfg.watch_dir, fname)
        if os.path.exists(dest) and self.cfg.on_conflict == "skip":
            # Already staged for Dreeve; leave it. Dedup by content is Dreeve's job.
            return fname
        tmp = dest + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(tcx)
        os.replace(tmp, dest)
        return fname

    def _write_status(self, res: CycleResult) -> None:
        status = {
            "lastCycleAt": _now_ms(),
            "lastCycle": res.as_dict(),
            "ledger": self.ledger.counts(),
        }
        os.makedirs(self.cfg.state_dir, exist_ok=True)
        p = os.path.join(self.cfg.state_dir, "status.json")
        with open(p, "w") as f:
            json.dump(status, f, indent=2)


def _fmt_date(ms) -> str:
    if not ms:
        return "?"
    import datetime
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
