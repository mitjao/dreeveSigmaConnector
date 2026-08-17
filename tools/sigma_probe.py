#!/usr/bin/env python3
"""
sigma_probe.py — Discover the SIGMA Cloud sync protocol against a real account.

Throwaway diagnostic tool (NOT the connector). It logs in to SIGMA Cloud via the
authorization-code flow the official DATA CENTER app uses, then dumps exactly
what `GET /sync` returns, so we know the data format before building the importer.

Auth flow (reverse-engineered from CloudWorker.swf):
  1. GET  /oauth/authorize?response_type=code&client_id=..&redirect_uri=..  -> 302 /login (session cookie)
  2. POST /login.do  (j_username, j_password)                               -> Spring form login
  3. GET  /oauth/authorize?...  (now authenticated)                         -> 302 <redirect_uri>?code=..
  4. POST /oauth/token  (grant_type=authorization_code, code, redirect_uri) -> access_token
  5. GET  /sync?access_token=..                                             -> the data

Stdlib only. Nothing is uploaded; responses are written next to this script.

Env vars (or interactive prompts):
  SIGMA_CLIENT_ID, SIGMA_CLIENT_SECRET   # from tools/extract_client_creds.py (MAC pair)
  SIGMA_USER, SIGMA_PASS                 # your SIGMA Cloud email + password
"""

import base64
import getpass
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.sigma-data-cloud.com"
REDIRECT_URI = "https://www.sigma-dc-control.com"  # registered redirect_uri of the DATA CENTER client
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
UA = "SIGMA DATA CENTER"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never auto-follow; we inspect every 3xx Location ourselves."""
    def redirect_request(self, *a, **k):
        return None


def build_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _NoRedirect()
    )
    opener.addheaders = [("User-Agent", UA)]
    return opener, jar


DEBUG = os.environ.get("SIGMA_DEBUG", "1") != "0"


def _short(url):
    p = urllib.parse.urlparse(url)
    q = ("?" + p.query[:60] + "…") if p.query else ""
    return f"{p.scheme}://{p.netloc}{p.path}{q}" if p.netloc else url


def do(opener, method, url, data=None, headers=None):
    hdrs = {"Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        r = opener.open(req, timeout=120)
        status, hd, payload = r.getcode(), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, hd, payload = e.code, dict(e.headers), e.read()
    if DEBUG:
        loc = hd.get("Location", "")
        tail = f"  ->  {_short(loc)}" if loc else f"  ({len(payload)}b)"
        print(f"      · {method} {_short(url)}  [{status}]{tail}")
    return status, hd, payload


def prompt(name, env, secret=False):
    v = os.environ.get(env)
    if v:
        return v
    # Allow reading the value from a file (e.g. SIGMA_PASS_FILE), so it never
    # touches the command line or shell history, and works with no TTY.
    fpath = os.environ.get(env + "_FILE")
    if not fpath and secret:
        default_file = os.path.join(OUT_DIR, ".sigma_pass")
        if os.path.exists(default_file):
            fpath = default_file
    if fpath and os.path.exists(fpath):
        with open(fpath) as f:
            return f.read().strip()
    try:
        return getpass.getpass(f"{name}: ") if secret else input(f"{name}: ").strip()
    except (EOFError, OSError):
        sys.exit(
            f"[!] Cannot prompt for {name} (no interactive terminal).\n"
            f"    Provide it via env {env}=… or a file: "
            f"printf '%s' 'value' > {os.path.join(OUT_DIR, '.sigma_pass')}"
            if secret else f"[!] Cannot read {name}: no terminal. Set {env}=…"
        )


def describe(raw):
    head = raw[:16]
    if raw[:3] in (b"CWS", b"FWS", b"ZWS"):
        return "swf"
    if head[:2] == b"PK":
        return "zip"
    if head[:1] in (b"{", b"["):
        return "json"
    if head[:1] == b"<":
        return "xml"
    if b".FIT" in raw[:32]:
        return "fit"
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in raw[:512])
    return "text-ish" if printable > 480 else "binary"


def print_shape(obj, indent=0, depth=0):
    pad = " " * indent
    if depth > 3:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}: {type(v).__name__}({len(v)})")
                print_shape(v, indent + 2, depth + 1)
            else:
                print(f"{pad}{k}: {type(v).__name__} = {repr(v)[:70]}")
    elif isinstance(obj, list):
        print(f"{pad}[{len(obj)} items]")
        if obj:
            print_shape(obj[0], indent + 2, depth + 1)


def get_code(opener, client_id):
    """Walk the authorize→login→authorize chain, return the auth code."""
    authorize = f"{BASE}/oauth/authorize?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI}
    )
    # 1. prime the session (302 -> /login)
    do(opener, "GET", authorize)

    # 2. form login
    user = prompt("SIGMA_USER (email)", "SIGMA_USER")
    password = prompt("SIGMA_PASS", "SIGMA_PASS", secret=True)
    status, headers, _ = do(
        opener, "POST", f"{BASE}/login.do",
        data={"j_username": user, "j_password": password, "remember-me": "on"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    loc = headers.get("Location", "")
    if "error" in loc.lower():
        sys.exit(f"[!] Login rejected (Location={loc}). Check email/password.")

    # 3. Spring redirects the successful login to the saved authorize request.
    #    Follow that chain (staying on sigma-data-cloud.com) until the code shows.
    url = loc if loc.startswith("http") else urllib.parse.urljoin(BASE, loc or authorize)
    seen_login = 0
    for _ in range(10):
        status, headers, body = do(opener, "GET", url)
        loc = headers.get("Location", "")
        if loc.startswith(REDIRECT_URI):
            q = urllib.parse.urlparse(loc).query
            params = urllib.parse.parse_qs(q)
            if "code" in params:
                return params["code"][0]
            sys.exit(f"[!] Redirect had no code: {loc}")
        if loc:
            if "/login" in loc:
                seen_login += 1
                if seen_login >= 2:
                    sys.exit("[!] Bounced back to /login — the session isn't "
                             "authenticated. Login likely failed (wrong password) "
                             "or the login form fields differ.")
            url = loc if loc.startswith("http") else urllib.parse.urljoin(BASE, loc)
            continue
        # Not a redirect: the consent/approval page. Approve, and read the code
        # straight off the approval POST's redirect (don't loop back to authorize).
        if status == 200:
            st2, hd2, _ = do(
                opener, "POST", f"{BASE}/oauth/authorize",
                data={"user_oauth_approval": "true", "scope.read": "true",
                      "scope.write": "true", "authorize": "Authorize"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            loc2 = hd2.get("Location", "")
            if loc2.startswith(REDIRECT_URI):
                params = urllib.parse.parse_qs(urllib.parse.urlparse(loc2).query)
                if "code" in params:
                    return params["code"][0]
            sys.exit(f"[!] Approval POST did not yield a code (HTTP {st2}, Location={loc2}).")
        sys.exit(f"[!] Unexpected authorize response: HTTP {status}, no Location. "
                 f"First bytes: {body[:200]!r}")
    sys.exit("[!] Too many redirects while getting the auth code.")


def main():
    client_id = prompt("SIGMA_CLIENT_ID", "SIGMA_CLIENT_ID")
    client_secret = prompt("SIGMA_CLIENT_SECRET", "SIGMA_CLIENT_SECRET", secret=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    opener, _jar = build_opener()

    print("\n[1/3] authorization-code login ...")
    code = get_code(opener, client_id)
    print(f"      got auth code: {code[:6]}…")

    # 4. exchange code for token
    print("[2/3] exchanging code for access_token ...")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    status, headers, raw = do(
        opener, "POST", f"{BASE}/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        tok = json.loads(raw)
    except Exception:
        tok = None
    token = tok.get("access_token") if isinstance(tok, dict) else None

    redacted = dict(tok) if isinstance(tok, dict) else {"raw": raw.decode("utf-8", "replace")}
    for k in ("access_token", "refresh_token"):
        if redacted.get(k):
            redacted[k] = redacted[k][:6] + "…(redacted)"
    with open(os.path.join(OUT_DIR, f"probe_token_{stamp}.json"), "w") as f:
        json.dump({"status": status, "body": redacted}, f, indent=2, ensure_ascii=False)

    if status != 200 or not token:
        sys.exit(f"[!] Token exchange failed: HTTP {status} — {raw[:200]!r}")
    print(f"      access_token OK (expires_in={tok.get('expires_in')}, scope={tok.get('scope')})")

    # 5. sync download — POST /sync?access_token=X, JSON body, per data type.
    #    Empty `list` + lastSyncDate 0 asks the server for a full dump.
    sync_url = f"{BASE}/sync?" + urllib.parse.urlencode({"access_token": token})
    print("[3/3] POST /sync (JSON sync-list) — trying data type 'Activity' ...")

    # Correct shape (from CommonCloudHandler.generateSyncList): a `dataList`
    # wrapper with {type, lastSync, list}. lastSync 0 = full download.
    bodies = [
        {"dataList": {"type": "ACTIVITY", "lastSync": 0, "list": []}},
        {"dataList": {"type": "TRACK", "lastSync": 0, "list": []}},
        {"dataList": {"type": "DEVICE", "lastSync": 0, "list": []}},
        {"dataList": {"type": "DATA", "lastSync": 0, "list": []}},
    ]
    # A cookie-free opener — the sync endpoint is a stateless OAuth resource
    # server; the authenticated web-login session may confuse it.
    plain = urllib.request.build_opener(_NoRedirect())
    plain.addheaders = [("User-Agent", UA)]

    sync_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Authorization": f"Bearer {token}",
    }

    chosen = None
    globals()["DEBUG"] = False  # the matrix prints its own concise line per attempt
    for label, op in (("cookieless", plain), ("session", opener)):
        print(f"      -- via {label} session --")
        for i, payload in enumerate(bodies, 1):
            body = json.dumps(payload).encode()
            status, headers, raw = do(op, "POST", sync_url, data=body, headers=sync_headers)
            kind = describe(raw)
            snippet = raw[:120].decode("utf-8", "replace").replace("\n", " ")
            print(f"      #{i:>2} {json.dumps(payload)[:52]:<52} -> {status} "
                  f"{len(raw):>5}b {kind:<7} {snippet[:46]}")
            if status == 200 and raw:
                chosen = (payload, status, headers, raw, kind)
                break
        if chosen:
            break

    if not chosen:
        print("\n[!] No body shape returned 200. The last response body was:")
        print("    " + raw[:300].decode("utf-8", "replace"))
        print("    Paste this to me and I'll adjust the request shape.")
        return

    payload, status, headers, raw, kind = chosen
    ext = {"json": "json", "xml": "xml", "zip": "zip", "fit": "fit"}.get(kind, "bin")
    sync_path = os.path.join(OUT_DIR, f"probe_sync_{stamp}.{ext}")
    with open(sync_path, "wb") as f:
        f.write(raw)
    with open(os.path.join(OUT_DIR, f"probe_sync_headers_{stamp}.json"), "w") as f:
        json.dump({"request_body": payload, "status": status, "headers": headers},
                  f, indent=2, ensure_ascii=False)
    print(f"      saved: {sync_path}")

    items = []
    if kind == "json":
        try:
            data = json.loads(raw)
            print("\n      JSON top-level shape:")
            print_shape(data, indent=8)
            # Response: {"dataLists":[{"type":"ACTIVITY","dataList":[{GUID,url,...}]}]}
            dl = (data.get("dataLists") or [{}])[0]
            items = dl.get("dataList") or []
            print(f"\n      {len(items)} activities in list. First item keys: "
                  f"{list(items[0].keys()) if items else '—'}")
        except Exception as e:
            print(f"      (JSON parse failed: {e})")

    # 6. Pull ONE real activity file so we can see the actual format (ZIP→SLF/XML).
    first_url = next((it.get("url") for it in items if it.get("url")), None)
    if first_url:
        print(f"\n[4/4] downloading one activity file:\n      {first_url[:90]}…")
        # Pre-signed S3 URL: it is self-authenticating; sending an extra
        # Authorization header makes S3 reject it (400). Send none.
        st, hd, blob = do(plain, "GET", first_url, headers={})
        k = describe(blob)
        act_path = os.path.join(OUT_DIR, f"probe_activity_{stamp}.{ 'zip' if k=='zip' else k if k in ('xml','fit') else 'bin'}")
        with open(act_path, "wb") as f:
            f.write(blob)
        print(f"      -> HTTP {st}, {len(blob)} bytes, {hd.get('Content-Type','?')}, looks like: {k}")
        print(f"      saved: {act_path}")
        if k == "zip":
            try:
                import io
                import zipfile
                zf = zipfile.ZipFile(io.BytesIO(blob))
                print(f"      zip entries: {zf.namelist()}")
                inner = zf.read(zf.namelist()[0])
                slf_path = os.path.join(OUT_DIR, f"probe_activity_{stamp}.slf")
                with open(slf_path, "wb") as f:
                    f.write(inner)
                text = inner[:600].decode("utf-8", "replace")
                print(f"      extracted first entry -> {slf_path} ({len(inner)} bytes)")
                print("      first 600 chars:\n" + "\n".join("        " + l for l in text.splitlines()))
            except Exception as e:
                print(f"      (unzip failed: {e})")

    print("\nDone. Share the probe_sync_* and probe_activity_* files with me")
    print("(privately — they contain your training data).")


if __name__ == "__main__":
    main()
