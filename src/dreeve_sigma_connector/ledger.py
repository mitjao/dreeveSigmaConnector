"""
A tiny JSON ledger of delivered activities, for dedup and resumable backfill.

Keyed by activity GUID -> {modificationDate, deliveredAt, file}. An activity is
re-delivered only when its modificationDate on the server is newer than what we
recorded (i.e. it was edited), matching Dreeve's own duplicate handling.
"""

from __future__ import annotations

import json
import os


class Ledger:
    def __init__(self, state_dir: str):
        self.path = os.path.join(state_dir, "ledger.json")
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._data = json.load(f)
            except (ValueError, OSError):
                self._data = {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=0)
        os.replace(tmp, self.path)

    def needs_delivery(self, guid: str, modification_date) -> bool:
        rec = self._data.get(guid)
        if rec is None:
            return True
        prev = rec.get("modificationDate") or 0
        return (modification_date or 0) > prev

    def mark(self, guid: str, modification_date, filename: str, delivered_at_ms: int) -> None:
        self._data[guid] = {
            "modificationDate": modification_date,
            "file": filename,
            "deliveredAt": delivered_at_ms,
        }

    def counts(self) -> dict:
        return {"delivered": len(self._data)}

    def __contains__(self, guid: str) -> bool:
        return guid in self._data
