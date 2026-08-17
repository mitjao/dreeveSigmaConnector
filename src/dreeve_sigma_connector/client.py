"""
SIGMA Cloud sync client (download side only).

Endpoint (reverse-engineered from CommonCloudHandler):
  POST /sync?access_token=<token>   Content-Type: application/json
  body: {"dataList": {"type": "<TYPE>", "lastSync": <ms>, "list": []}}
  ->    {"dataTimestamp": <ms>,
         "dataLists": [{"type": "<TYPE>", "dataList": [
             {"GUID": "...", "modificationDate": <ms>, "status": "DOWNLOAD",
              "activityDate": <ms>, "url": "<pre-signed S3 URL>"}, ...]}]}

Each activity `url` is a pre-signed S3 link to a ZIP containing one `.slf`
(SIGMA Log Format XML). The pre-signed URL must be fetched with NO extra auth
headers.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .config import BASE_URL

log = logging.getLogger("sigma.client")
UA = "SIGMA DATA CENTER"

# Sync types (from CommonCloudHandler.startXxxSynchronisation).
TYPE_ACTIVITY = "ACTIVITY"
TYPE_TRACK = "TRACK"
TYPE_DEVICE = "DEVICE"
TYPE_DATA = "DATA"


class SigmaClientError(Exception):
    pass


class InvalidTokenError(SigmaClientError):
    pass


class SigmaCloudClient:
    def __init__(self, access_token: str):
        self.token = access_token
        self._opener = urllib.request.build_opener()
        self._opener.addheaders = [("User-Agent", UA)]

    # -- low level ---------------------------------------------------------
    def _post_sync(self, body: dict) -> bytes:
        url = f"{BASE_URL}/sync?access_token={urllib.parse.quote(self.token)}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Cache-Control": "no-cache",
                     "User-Agent": UA},
        )
        try:
            with self._opener.open(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            payload = e.read()
            if e.code in (401, 403) or b"invalid_token" in payload:
                raise InvalidTokenError("Access token rejected by /sync — re-login needed.")
            raise SigmaClientError(f"/sync HTTP {e.code}: {payload[:200]!r}")

    # -- public ------------------------------------------------------------
    def list_activities(self, last_sync_ms: int = 0) -> list[dict]:
        """Return the server's activity list (items with GUID, url, modificationDate…)."""
        raw = self._post_sync(
            {"dataList": {"type": TYPE_ACTIVITY, "lastSync": last_sync_ms, "list": []}}
        )
        obj = json.loads(raw)
        lists = obj.get("dataLists") or []
        if not lists:
            return []
        return lists[0].get("dataList") or []

    def download_slf(self, url: str) -> bytes:
        """Fetch a pre-signed activity URL and return the inner .slf bytes."""
        # No auth headers: the S3 URL is self-signed.
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                blob = r.read()
        except urllib.error.HTTPError as e:
            raise SigmaClientError(f"activity download HTTP {e.code}: {e.read()[:150]!r}")
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
            names = zf.namelist()
            if not names:
                raise SigmaClientError("activity ZIP is empty")
            return zf.read(names[0])
        except zipfile.BadZipFile:
            # Some payloads might already be raw XML.
            if blob[:64].lstrip().startswith(b"<"):
                return blob
            raise SigmaClientError("activity payload is neither ZIP nor XML")
