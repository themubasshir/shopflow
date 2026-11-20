"""Human-in-the-loop browser fetcher for authorized MedEx collection (Phase 3D).

Drives a **visible, persistent-profile Chromium** via Playwright so the shop
owner can complete MedEx's security challenge by hand when the WAF presents
one. It implements the same ``fetch_index`` / ``fetch_detail`` contract as the
HTTP ``LiveFetcher`` so the existing importer, checkpointing, deduplication,
and promote pipeline run unchanged on top of it.

Deliberate boundaries — this is *not* a bypass tool:

* No stealth plugins, no fingerprint/UA spoofing, no proxy rotation, no
  CAPTCHA-solving service, no challenge-token reuse. The browser is a real,
  honest Chromium with a persistent profile the owner controls.
* When a security gate is detected the fetcher **pauses and waits for a
  human** to clear it in the visible window, then *verifies* a real medicine
  page came back before continuing. It never fabricates a pass.
* Conservative pacing is preserved (a floor of a few seconds between page
  loads, since a human-driven browser is inherently slower than httpx).

The browser profile lives under ``.local/browser_profile`` which is gitignored
— cookies/session state persist across runs so a cleared challenge stays
cleared for the session's lifetime.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from app.integrations.medex.client import FetchError

logger = logging.getLogger("shopflow.medex.browser")

# How long (seconds) to wait for the user to clear a challenge before giving up.
_GATE_WAIT_CAP = int(os.environ.get("MEDEX_GATE_WAIT", "900"))
# Poll interval while waiting for the gate to clear.
_GATE_POLL = 2.0


@dataclass
class _GateState:
    """Tracks a live security challenge so we pause once, not per-page."""

    active: bool = False
    cleared_at: float = 0.0


class BrowserFetcher:
    """Playwright-backed fetcher. ``fetch_index``/``fetch_detail`` mirror the
    HTTP fetcher signatures so ``run_import`` needs no changes.

    ``pause_callback`` is invoked when a security gate blocks collection —
    the harness uses it to surface a prompt to the operator. If it returns
    False (user declined / can't clear), a FetchError is raised so the run
    checkpoints and stops rather than hammering the gate.
    """

    def __init__(
        self,
        *,
        base: str = "https://medex.com.bd",
        profile_dir: str = ".local/browser_profile",
        headless: bool = False,
        min_interval: float = 4.0,
        pause_callback=None,
        gate_wait: int = _GATE_WAIT_CAP,
    ):
        from playwright.sync_api import sync_playwright

        self.base = base.rstrip("/")
        self.min_interval = min_interval
        self.pause_callback = pause_callback
        self.gate_wait = gate_wait
        self._gate = _GateState()
        self._last_at = 0.0

        os.makedirs(profile_dir, exist_ok=True)
        self._pw = sync_playwright().start()
        # Persistent context = real profile on disk (cookies/session persist).
        # Visible window so the user can interact with a challenge.
        self._ctx = self._pw.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
            viewport={"width": 1280, "height": 900},
            accept_downloads=False,
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    # ------------------------------------------------------------------
    def _pace(self) -> None:
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_at)
        if wait > 0:
            time.sleep(wait)
        self._last_at = time.monotonic()

    def _is_gate(self, html: str, url: str) -> bool:
        if "captcha-challenge" in (self._page.url or url):
            return True
        head = html[:4000].lower()
        return (
            "security check" in head
            or "captcha-challenge" in head
            or ("cf-chl" in head)  # cloudflare challenge marker
            or ("just a moment" in head and "cloudflare" in head)
        )

    def _looks_like_medicine(self, html: str) -> bool:
        head = html.lower()
        return 'class="brand"' in head or "brand-card" in head or "package-container" in head

    def _load(self, url: str) -> str:
        """Navigate to ``url`` and return the rendered HTML, handling gates."""
        self._pace()
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            raise FetchError(url, None, f"browser nav: {exc}") from exc
        # brief settle for any client-side render
        time.sleep(0.6)
        html = self._page.content()

        if self._is_gate(html, url):
            html = self._handle_gate(url, html)
        return html

    def _handle_gate(self, url: str, html: str) -> str:
        """Pause for a human to clear the challenge, then re-verify access.

        Returns the medicine-page HTML on legitimate clearance; raises
        FetchError if the user can't/won't clear it within the wait cap so the
        caller checkpoints + stops."""
        logger.warning("medex security gate at %s — pausing for manual clear", url)
        print(f"\n[medex] SECURITY GATE at {url}")
        print("[medex] Solve the challenge in the browser window, then press Enter here.")

        allowed = True
        if self.pause_callback is not None:
            allowed = bool(self.pause_callback(url))
        else:
            # No harness wired: poll the page until the gate clears or cap.
            deadline = time.monotonic() + self.gate_wait
            while time.monotonic() < deadline:
                time.sleep(_GATE_POLL)
                html = self._page.content()
                if not self._is_gate(html, self._page.url or url):
                    break
            else:
                allowed = False

        if not allowed:
            raise FetchError(url, 403, "security gate not cleared (manual abort)")

        # Re-verify: the *current* page must now be the medicine page, not the
        # gate. Reload the target once to be sure we're looking at the real URL.
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(0.6)
            html = self._page.content()
        except Exception as exc:
            raise FetchError(url, None, f"browser reverify: {exc}") from exc

        if self._is_gate(html, self._page.url or url):
            raise FetchError(url, 403, "still gated after manual clear")
        if not self._looks_like_medicine(html):
            raise FetchError(url, 200, "page cleared but not a medicine page")
        self._gate.cleared_at = time.time()
        logger.info("medex gate cleared; access verified at %s", url)
        return html

    # ------------------------------------------------------------------
    # IndexFetcher protocol
    # ------------------------------------------------------------------
    def fetch_index(self, page: int) -> tuple[str, str]:
        url = f"{self.base}/brands" if page <= 1 else f"{self.base}/brands?page={page}"
        return self._load(url), url

    def fetch_detail(self, url: str) -> tuple[str, bytes]:
        html = self._load(url)
        return html, html.encode("utf-8")

    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> BrowserFetcher:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
