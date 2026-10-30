"""Read-only HTTP client.

Safety design:
  * Only GET requests to an explicit allow-list of paths are possible.
  * The single POST that exists is the site's own login call (NextAuth credentials).
  * No Delete / Edit / Cancel / Activity-log / OCR / NID endpoints are reachable,
    because they are simply not in the allow-list.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (VerifyReportBuilder/1.0; read-only)"

_ALLOWED_GET = [
    re.compile(p)
    for p in (
        r"^/api/auth/providers$",
        r"^/api/auth/csrf$",
        r"^/api/auth/session$",
        r"^/api/v2/auth/user$",
        r"^/api/v2/manager/applications$",
        r"^/api/v2/manager/applications/\d+$",
    )
]
_LOGIN_PATH = "/api/auth/callback/credentials"


class AuthError(Exception):
    """Wrong credentials or expired token."""


class ApiError(Exception):
    """Any other request failure (after retries)."""


class Cancelled(Exception):
    """User pressed cancel."""


class ReadOnlyClient:
    def __init__(self, web_base: str, api_base: str, timeout: float = 40.0, retries: int = 4,
                 cancel: threading.Event | None = None):
        self.web = web_base.rstrip("/")
        self.api = api_base.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.cancel = cancel or threading.Event()
        self.token: str | None = None
        self._local = threading.local()
        self._web_session = requests.Session()
        self._web_session.headers.update({"User-Agent": USER_AGENT})

    # ------------------------------------------------------------------ helpers
    def _thread_session(self) -> requests.Session:
        s = getattr(self._local, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": USER_AGENT})
            self._local.s = s
        return s

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check_cancel()
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    # ------------------------------------------------------------------ login
    def login(self, email: str, password: str) -> dict:
        """Run the site's own login flow and return the session JSON (contains accessToken)."""
        s = self._web_session
        try:
            s.get(f"{self.web}/api/auth/providers", timeout=self.timeout)
            r = s.get(f"{self.web}/api/auth/csrf", timeout=self.timeout)
            r.raise_for_status()
            csrf = r.json()["csrfToken"]
            r = s.post(
                self.web + _LOGIN_PATH,
                data={
                    "email": email,
                    "password": password,
                    "rememberMe": "true",
                    "csrfToken": csrf,
                    "callbackUrl": f"{self.web}/login",
                },
                headers={"Origin": self.web, "Referer": f"{self.web}/login"},
                timeout=self.timeout,
            )
            if r.status_code >= 500:
                raise ApiError(f"লগইন সার্ভারে সমস্যা (HTTP {r.status_code})")
            r = s.get(f"{self.web}/api/auth/session", timeout=self.timeout)
            r.raise_for_status()
            session = r.json() or {}
        except requests.RequestException as exc:
            raise ApiError(f"সার্ভারে সংযোগ করা যায়নি: {type(exc).__name__}") from None
        token = session.get("accessToken")
        if not token:
            raise AuthError("লগইন হয়নি। ইমেইল বা পাসওয়ার্ড ভুল হতে পারে।")
        self.token = token
        return session

    # ------------------------------------------------------------------ GET (API)
    def get(self, path: str, params: list[tuple[str, Any]] | None = None) -> Any:
        if not any(p.match(urlparse(path).path) for p in _ALLOWED_GET):
            raise PermissionError(f"অনুমোদিত নয় (শুধু পড়ার অনুরোধ চলবে): {path}")
        if not self.token:
            raise AuthError("লগইন করা নেই।")
        url = self.api + path
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Origin": self.web,
            "Referer": self.web + "/",
        }
        last = "unknown"
        for attempt in range(1, self.retries + 1):
            self._check_cancel()
            try:
                r = self._thread_session().get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last = type(exc).__name__
            else:
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError:
                        last = "invalid JSON"
                elif r.status_code in (401, 403):
                    raise AuthError(f"টোকেন গ্রহণ হয়নি (HTTP {r.status_code})। আবার লগইন করুন।")
                elif r.status_code == 429:
                    last = "HTTP 429"
                    try:
                        wait = float(r.headers.get("Retry-After", ""))
                    except ValueError:
                        wait = 5.0
                    self._sleep(min(wait, 30.0))
                    continue
                elif r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                elif r.status_code == 404:
                    raise ApiError("HTTP 404 (পাওয়া যায়নি)")
                else:
                    raise ApiError(f"HTTP {r.status_code}")
            if attempt < self.retries:
                self._sleep(1.5 * attempt)
        raise ApiError(f"{self.retries} বার চেষ্টার পরও ব্যর্থ ({last})")
