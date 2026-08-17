"""
SIGMA Cloud authentication — the OAuth2 authorization-code flow the official
DATA CENTER app uses (reverse-engineered from CloudWorker.swf):

  1. GET  /oauth/authorize?response_type=code&client_id=..&redirect_uri=..  -> 302 /login
  2. POST /login.do  (j_username, j_password)                               -> Spring form login
  3. GET  /oauth/authorize (authenticated) / POST consent                   -> 303 <redirect_uri>?code=..
  4. POST /oauth/token  (grant_type=authorization_code, code, redirect_uri) -> access_token

The issued token is effectively non-expiring (expires_in ~50 years) and the
client is NOT allowed the refresh_token grant, so we simply persist the access
token and re-run this whole flow only if it is ever rejected.
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from .config import BASE_URL, REDIRECT_URI

log = logging.getLogger("sigma.auth")
UA = "SIGMA DATA CENTER"


class AuthError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _opener():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
    op.addheaders = [("User-Agent", UA)]
    return op


def _req(op, method, url, data=None, headers=None):
    hdrs = {"Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        r = op.open(req, timeout=60)
        return r.getcode(), dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def login(email: str, password: str, client_id: str, client_secret: str) -> dict:
    """Run the full authorization-code flow and return the token JSON dict."""
    if not email or not password:
        raise AuthError("SIGMA_EMAIL and SIGMA_PASSWORD are required to log in.")
    op = _opener()
    authorize = f"{BASE_URL}/oauth/authorize?" + urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI}
    )
    _req(op, "GET", authorize)  # prime session -> /login

    status, headers, _ = _req(
        op, "POST", f"{BASE_URL}/login.do",
        data={"j_username": email, "j_password": password, "remember-me": "on"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    loc = headers.get("Location", "")
    if "error" in loc.lower():
        raise AuthError("Login rejected — check SIGMA_EMAIL / SIGMA_PASSWORD.")

    code = _walk_for_code(op, loc or authorize, authorize)

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    status, headers, raw = _req(
        op, "POST", f"{BASE_URL}/oauth/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    if status != 200:
        raise AuthError(f"Token exchange failed: HTTP {status} — {raw[:200]!r}")
    tok = json.loads(raw)
    if not tok.get("access_token"):
        raise AuthError(f"No access_token in token response: {raw[:200]!r}")
    return tok


def _walk_for_code(op, start_url, authorize_url):
    seen_login = 0
    url = start_url if start_url.startswith("http") else urllib.parse.urljoin(BASE_URL, start_url)
    for _ in range(10):
        status, headers, body = _req(op, "GET", url)
        loc = headers.get("Location", "")
        if loc.startswith(REDIRECT_URI):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
            if "code" in params:
                return params["code"][0]
            raise AuthError(f"Redirect carried no code: {loc}")
        if loc:
            if "/login" in loc:
                seen_login += 1
                if seen_login >= 2:
                    raise AuthError("Bounced to /login — session not authenticated.")
            url = loc if loc.startswith("http") else urllib.parse.urljoin(BASE_URL, loc)
            continue
        if status == 200:  # consent page -> approve, read code off the redirect
            st, hd, _ = _req(
                op, "POST", f"{BASE_URL}/oauth/authorize",
                data={"user_oauth_approval": "true", "scope.read": "true",
                      "scope.write": "true", "authorize": "Authorize"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            loc2 = hd.get("Location", "")
            if loc2.startswith(REDIRECT_URI):
                params = urllib.parse.parse_qs(urllib.parse.urlparse(loc2).query)
                if "code" in params:
                    return params["code"][0]
            raise AuthError(f"Approval did not yield a code (HTTP {st}, Location={loc2}).")
    raise AuthError("Too many redirects while obtaining the auth code.")


# --- token persistence ------------------------------------------------------

def token_path(token_dir: str) -> str:
    return os.path.join(token_dir, "token.json")


def save_token(token_dir: str, tok: dict) -> None:
    os.makedirs(token_dir, exist_ok=True)
    p = token_path(token_dir)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tok, f)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def load_token(token_dir: str) -> dict | None:
    p = token_path(token_dir)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)
