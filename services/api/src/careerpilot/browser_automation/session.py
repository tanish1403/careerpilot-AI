"""Explicit, user-started browser sessions.

One dedicated worker thread owns each Playwright browser (the sync API is thread-affine). Contexts
are EPHEMERAL: no saved browser state, no persistent profile - cookies are treated as secrets and die
with the session. Every request is screened: non-GET methods are aborted (defence in depth: the
automation can never POST a form) and navigations to non-allowlisted hosts - including redirect
hops - are aborted.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Callable
from urllib.parse import urljoin

from .allowlist import is_allowed
from .safety import Blocker, detect_blockers

log = logging.getLogger("careerpilot.automation")
NAV_TIMEOUT_MS = 20_000
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class BrowserUnavailable(RuntimeError):
    pass


class BrowserWorker:
    def __init__(self, allowlist: list[str], headed: bool = False):
        self.allowlist = [a.lower() for a in allowlist]
        self.headed = headed
        self.violations: list[str] = []
        self.blocked_methods = 0
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="cp-browser", daemon=True)
        self.closed = False

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(60)
        if self._error is not None:
            raise BrowserUnavailable(f"{type(self._error).__name__}: {self._error}")

    # ---- thread body -----------------------------------------------------------------------
    def _guard(self, route, request) -> None:  # noqa: ANN001
        if request.method not in _SAFE_METHODS:
            self.blocked_methods += 1
            route.abort()
            return
        if request.is_navigation_request() and not is_allowed(request.url, self.allowlist):
            self.violations.append(f"navigation blocked: host not allowlisted "
                                   f"({_host_for_log(request.url)})")
            route.abort()
            return
        if request.is_navigation_request():
            # Playwright does not re-route redirect hops, so resolve redirects ourselves: fetch
            # without following, vet the Location header, and only then hand the response over.
            try:
                resp = route.fetch(max_redirects=0)
                if 300 <= resp.status < 400 and resp.headers.get("location"):
                    target = urljoin(request.url, resp.headers["location"])
                    if not is_allowed(target, self.allowlist):
                        self.violations.append(f"redirect blocked: host not allowlisted "
                                               f"({_host_for_log(target)})")
                        route.abort()
                        return
                route.fulfill(response=resp)
            except Exception:  # noqa: BLE001
                route.abort()
            return
        route.continue_()

    def _run(self) -> None:
        pw = browser = None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=not self.headed)
            ctx = browser.new_context(accept_downloads=False, service_workers="block",
                                      viewport={"width": 1280, "height": 900})
            ctx.route("**/*", self._guard)
            self.page = ctx.new_page()
        except BaseException as e:  # noqa: BLE001
            self._error = e
            self._ready.set()
            self._cleanup(pw, browser)
            return
        self._ready.set()
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, fut = item
            try:
                fut.set_result(fn(self.page))
            except BaseException as e:  # noqa: BLE001
                fut.set_exception(e)
        self._cleanup(pw, browser)

    @staticmethod
    def _cleanup(pw, browser) -> None:  # noqa: ANN001
        for obj, meth in ((browser, "close"), (pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:  # noqa: BLE001
                pass

    # ---- api -------------------------------------------------------------------------------
    def call(self, fn: Callable[[Any], Any], timeout: float = 90) -> Any:
        if self.closed:
            raise BrowserUnavailable("session closed")
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._q.put(None)
        self._thread.join(15)

    def goto(self, url: str) -> list[Blocker]:
        """Navigate (allowlist already checked by the caller) and report hard-stop conditions."""
        def _go(page):  # noqa: ANN001
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_load_state("load", timeout=5000)
            except Exception as e:  # noqa: BLE001
                if not self.violations:
                    self.violations.append(f"navigation failed: {type(e).__name__}")
            blockers = detect_blockers(page, [])
            if page.url and page.url != "about:blank" and not is_allowed(page.url, self.allowlist):
                self.violations.append(f"final url host not allowlisted ({_host_for_log(page.url)})")
            for v in dict.fromkeys(self.violations):
                blockers.insert(0, Blocker("navigation_failed" if v.startswith("navigation failed")
                                           else "domain_not_allowed", v))
            return blockers
        return self.call(_go)


def _host_for_log(url: str) -> str:
    from .allowlist import host_of
    return host_of(url) or "?"


class AutomationSession:
    def __init__(self, application_id: str, url: str, worker: BrowserWorker):
        self.id = uuid.uuid4().hex
        self.application_id = application_id
        self.url = url
        self.worker = worker
        self.status = "open"            # open|blocked|review|stopped
        self.blockers: list[dict] = []
        self.adapter_name: str | None = None
        self.fields: list = []          # FormField list from last extraction
        self.adapter = None
        self.review: dict | None = None
        self.created_at = time.time()
        self.lock = threading.Lock()

    def public(self) -> dict:
        return {"id": self.id, "application_id": self.application_id, "status": self.status,
                "url": self.url, "headed": self.worker.headed, "adapter": self.adapter_name,
                "blockers": self.blockers, "review": self.review,
                "created_at": self.created_at}


class SessionManager:
    def __init__(self) -> None:
        self._s: dict[str, AutomationSession] = {}
        self._lock = threading.Lock()

    def add(self, s: AutomationSession) -> None:
        with self._lock:
            self._s[s.id] = s

    def get(self, sid: str) -> AutomationSession | None:
        return self._s.get(sid)

    def active_for(self, application_id: str) -> AutomationSession | None:
        for s in list(self._s.values()):
            if s.application_id == application_id and s.status != "stopped":
                return s
        return None

    def shutdown_all(self) -> None:
        with self._lock:
            sessions = list(self._s.values())
            self._s.clear()
        for s in sessions:
            s.worker.close()
            s.status = "stopped"


MANAGER = SessionManager()
