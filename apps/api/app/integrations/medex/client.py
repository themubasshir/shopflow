"""Throttled HTTPX client for the authorized MedEx collection.

Defaults are deliberately conservative — single concurrency, ~1 request per
``min_interval`` seconds — because the exact rate limit in the written
authorization is not yet codified. The limits are constructor-injected so a
run can be tuned to whatever the consent specifies without code changes.

* Global ``min_interval`` pacing between requests (per client instance).
* Retries with exponential backoff + jitter on 429 / 5xx / network errors.
* ``Retry-After`` honoured when present (capped so a hostile header can't
  stall a run for hours).
* A descriptive, honest ``User-Agent`` — no spoofing, no header games.
* Per-request timeout. No CAPTCHA / auth bypass ever.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("shopflow.medex")

_DEFAULT_UA = "ShopFlow-CatalogImporter/0.1 (+contact: shopflow-admin; authorized-collection)"
# Errors worth retrying (rate-limit + transient server/network).
_RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes
    text: str
    retries: int = 0


class FetchError(Exception):
    """A page could not be fetched after the retry budget."""

    def __init__(self, url: str, status: int | None, detail: str):
        super().__init__(f"{url}: {detail}")
        self.url = url
        self.status = status
        self.detail = detail


@dataclass
class MedexClient:
    base_url: str = "https://medex.com.bd"
    min_interval: float = 2.0  # seconds between requests
    timeout: float = 30.0
    max_retries: int = 4
    backoff_base: float = 2.0
    max_retry_after: float = 60.0
    user_agent: str = _DEFAULT_UA
    _client: httpx.Client = field(init=False, repr=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    # ------------------------------------------------------------------
    def _pace(self) -> None:
        """Enforce the minimum gap between requests."""
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    # ------------------------------------------------------------------
    def get(self, path_or_url: str) -> FetchResult:
        """GET one page with pacing + retry. Returns raw text+bytes.

        Raises ``FetchError`` if the retry budget is exhausted or the response
        is a hard failure (4xx other than 429).
        """
        last_exc: Exception | None = None
        status: int | None = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            try:
                resp = self._client.get(path_or_url)
                status = resp.status_code
                if status == 200:
                    return FetchResult(
                        url=str(resp.url),
                        status=status,
                        content=resp.content,
                        text=resp.text,
                        retries=attempt,
                    )
                if status in _RETRY_STATUSES:
                    raise FetchError(str(resp.url), status, f"HTTP {status}")
                # Hard failure (404, 403, etc.) — do not retry.
                raise FetchError(str(resp.url), status, f"HTTP {status} (not retried)")
            except FetchError as exc:
                last_exc = exc
                if exc.status and exc.status not in _RETRY_STATUSES:
                    raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = FetchError(path_or_url, None, f"{type(exc).__name__}: {exc}")

            # Backoff with jitter; honour Retry-After when present & sane.
            delay = self.backoff_base**attempt + random.uniform(0, 0.5 * self.backoff_base)
            retry_after = None
            try:
                if "resp" in locals() and resp.headers.get("Retry-After"):
                    retry_after = min(float(resp.headers["Retry-After"]), self.max_retry_after)
            except (ValueError, TypeError):
                retry_after = None
            wait = max(delay, retry_after or 0)
            logger.info("medex retry %s attempt=%d wait=%.1fs", path_or_url, attempt + 1, wait)
            self._sleep(wait)

        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MedexClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
