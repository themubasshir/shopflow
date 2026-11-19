"""Print-agent core (Phase 2D-2).

The agent polls the API for work — it never listens on an inbound socket, so no
printer port is exposed to the internet. One loop iteration:

1. Authenticate (agent credential, independent of any cashier session).
2. Claim the oldest pending job for its printer (server lease + FIFO).
3. Exchange the job's one-time document token for a render grant.
4. Fetch the canonical PDF from the web render route.
5. Rasterize the PDF to a calibrated monochrome strip.
6. Convert to ESC/POS raster commands and stream via the transport.
7. Cut the paper when supported.
8. Report printing → completed, or failed with a sanitized error.

``PrintAgent`` is transport-agnostic: the simulator injects a fake transport,
the real deployment uses ``NetworkTransport``. A transport that raises mid-send
is reported as ``uncertain`` — the physical outcome is unknown and the job is
never auto-reprinted.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .raster import pdf_to_escpos
from .transport import PrinterTransport, TransportError, transport_for


class AgentError(Exception):
    """An unrecoverable agent-side failure (bad response shape, auth)."""


@dataclass
class HttpClient:
    """Minimal JSON/bytes client so the agent has no heavyweight HTTP dep.

    ``base`` is the API root (e.g. ``http://localhost:8001/api/v1``); ``web_base``
    is where the render route lives (e.g. ``http://localhost:3000``).
    """

    api_base: str
    web_base: str
    timeout: float = 30.0

    def post_json(self, path: str, payload: dict) -> dict:
        return self._json(f"{self.api_base}{path}", payload)

    def _json(self, url: str, payload: dict) -> dict:
        import json

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise AgentError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AgentError("API unreachable") from exc

    def fetch_bytes(self, path: str) -> bytes:
        url = f"{self.web_base}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise AgentError(f"Render fetch failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise AgentError("Render route unreachable") from exc


@dataclass
class AgentConfig:
    agent_id: str
    token: str
    api_base: str = "http://localhost:8001/api/v1"
    web_base: str = "http://localhost:3000"
    poll_seconds: float = 2.0


@dataclass
class AgentStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    uncertain: int = 0
    polls: int = 0


@dataclass
class PrintAgent:
    config: AgentConfig
    transport: PrinterTransport | None = None
    http: HttpClient | None = None
    stats: AgentStats = field(default_factory=AgentStats)
    _printer_config: dict | None = None
    _transport_name: str = "network"

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = HttpClient(api_base=self.config.api_base, web_base=self.config.web_base)

    # -- protocol -----------------------------------------------------

    def _credentials(self) -> dict:
        return {"agent_id": self.config.agent_id, "token": self.config.token}

    def _ensure_config(self) -> None:
        if self._printer_config is None:
            resp = self.http.post_json("/print/agent/config", self._credentials())
            self._printer_config = resp.get("config") or {}
            self._transport_name = resp.get("transport", "network")

    def _transport(self) -> PrinterTransport:
        if self.transport is not None:
            return self.transport
        return transport_for(self._transport_name)

    def resolve_transport(self) -> PrinterTransport:
        """Fetch this agent's printer config and return the transport to use.

        Called once before the polling loop so a misconfigured or unimplemented
        transport fails fast instead of after the first claimed job.
        """
        self._ensure_config()
        self.transport = self._transport()
        return self.transport

    def _report(self, job_id: str, claim_token: str, outcome: str, **kw) -> None:
        payload = {
            **self._credentials(),
            "job_id": job_id,
            "claim_token": claim_token,
            "outcome": outcome,
            **kw,
        }
        self.http.post_json("/print/agent/report", payload)

    # -- one job --------------------------------------------------------

    def process_next(self) -> bool:
        """Claim and process a single job. Returns True when a job ran."""
        self.stats.polls += 1
        self._ensure_config()
        claim = self.http.post_json("/print/agent/claim", self._credentials())
        job = claim.get("job")
        if job is None:
            return False
        self.stats.claimed += 1
        job_id = job["id"]
        claim_token = job["claim_token"]
        try:
            self._run_job(job, claim_token)
        except TransportError as exc:
            # Delivery may or may not have reached the printer: the outcome is
            # uncertain. Report 'failed' so the job is not silently reprinted;
            # an owner reprints explicitly.
            self._report(
                job_id,
                claim_token,
                "failed",
                error_code="transport_uncertain",
                error_message=str(exc)[:200],
            )
            self.stats.uncertain += 1
            return True
        except AgentError as exc:
            self._report(
                job_id, claim_token, "failed", error_code="render_failed", error_message=str(exc)[:200]
            )
            self.stats.failed += 1
            return True
        return True

    def _run_job(self, job: dict, claim_token: str) -> None:
        job_id = job["id"]
        # 1. Signal streaming has begun (moves the job to `printing`).
        self._report(job_id, claim_token, "printing")
        # 2. Exchange the document token for a render grant, then fetch the PDF.
        doc = self.http.post_json(
            "/print/agent/document",
            {**self._credentials(), "job_id": job_id, "document_token": job["document_token"]},
        )
        pdf = self.http.fetch_bytes(doc["render_url"])
        # 3. Rasterize to the printer's calibrated width and stream ESC/POS.
        stream = pdf_to_escpos(
            pdf, int(job["dots_width"]), has_cutter=bool(job["has_cutter"])
        )
        self._transport().send(stream, self._printer_config)
        # 4. Confirm the physical print completed.
        self._report(job_id, claim_token, "completed")
        self.stats.completed += 1

    # -- driver ---------------------------------------------------------

    def run(self, max_jobs: int | None = None, stop_after_idle: int | None = None) -> AgentStats:
        """Poll until ``max_jobs`` processed or ``stop_after_idle`` empty polls."""
        done = 0
        idle = 0
        while True:
            if max_jobs is not None and done >= max_jobs:
                break
            worked = self.process_next()
            if worked:
                done += 1
                idle = 0
            else:
                idle += 1
                if stop_after_idle is not None and idle >= stop_after_idle:
                    break
                time.sleep(self.config.poll_seconds)
        return self.stats

