"""Command-line entry point for the ShopFlow print agent.

Two modes:

* ``run`` — the real agent. Polls the API with its printer credential, claims
  jobs, fetches the canonical PDF from the web render route, rasterizes and
  streams ESC/POS to the printer over Wi-Fi/LAN.
* ``simulate`` — the hardware-free harness. Same claim → render → raster →
  stream → report loop, but the transport records bytes in memory instead of
  opening a socket, so the whole pipeline can be exercised in CI and on a
  laptop without a printer.

Both modes print a JSON summary and exit non-zero only on an unrecoverable
configuration/auth failure, so a supervisor can restart the process.
"""

from __future__ import annotations

import argparse
import json
import sys

from .agent import AgentConfig, HttpClient, PrintAgent
from .transport import SimulatedPrinter

DEFAULT_API = "http://localhost:8001/api/v1"
DEFAULT_WEB = "http://localhost:3000"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shopflow-print-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--agent-id", required=True, help="printer agent id from ShopFlow")
        target.add_argument("--token", required=True, help="one-time agent token from ShopFlow")
        target.add_argument("--api", default=DEFAULT_API, help=f"API root (default {DEFAULT_API})")
        target.add_argument("--web", default=DEFAULT_WEB, help=f"web root (default {DEFAULT_WEB})")
        target.add_argument("--poll", type=float, default=2.0, help="idle poll interval, seconds")
        target.add_argument("--max-jobs", type=int, default=None, help="stop after N jobs")
        target.add_argument("--idle-polls", type=int, default=None, help="stop after N empty polls")

    run = sub.add_parser("run", help="poll and print against real hardware")
    common(run)

    sim = sub.add_parser("simulate", help="same loop with an in-memory printer")
    common(sim)
    sim.add_argument(
        "--dump",
        default=None,
        help="write the last ESC/POS byte stream to this file for inspection",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AgentConfig(
        agent_id=args.agent_id,
        token=args.token,
        api_base=args.api,
        web_base=args.web,
        poll_seconds=args.poll,
    )
    http = HttpClient(api_base=args.api, web_base=args.web)

    if args.command == "simulate":
        sink: list[bytes] = []
        agent = PrintAgent(config=config, transport=SimulatedPrinter(sink=sink), http=http)
        try:
            stats = agent.run(max_jobs=args.max_jobs, stop_after_idle=args.idle_polls or 1)
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports and exits
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        if args.dump and sink:
            with open(args.dump, "wb") as handle:
                handle.write(sink[-1])
        print(
            json.dumps(
                {
                    "mode": "simulate",
                    "claimed": stats.claimed,
                    "completed": stats.completed,
                    "failed": stats.failed,
                    "uncertain": stats.uncertain,
                    "streams": len(sink),
                    "bytes": sum(len(chunk) for chunk in sink),
                }
            )
        )
        return 0

    agent = PrintAgent(config=config, transport=None, http=http)
    # Resolve the transport from the printer record before the loop so a
    # misconfigured/unimplemented transport fails fast and visibly.
    try:
        agent.resolve_transport()
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports and exits
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    try:
        stats = agent.run(max_jobs=args.max_jobs, stop_after_idle=args.idle_polls)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports and exits
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "mode": "run",
                "claimed": stats.claimed,
                "completed": stats.completed,
                "failed": stats.failed,
                "uncertain": stats.uncertain,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
