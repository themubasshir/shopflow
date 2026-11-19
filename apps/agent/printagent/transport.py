"""Printer transports (Phase 2D-2).

A ``PrinterTransport`` delivers a fully-formed ESC/POS byte stream to hardware.
The queue, renderer and claim protocol are transport-agnostic — adding
Bluetooth means writing a new transport class, nothing else.

Only ``NetworkTransport`` is implemented today (Wi-Fi/LAN TCP 9100, the de-facto
ESC/POS socket). ``BluetoothTransport`` is a declared placeholder: it raises a
clear error until a real Android/host implementation and a device test exist.
We do not claim Bluetooth hardware support without that evidence.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass


class TransportError(Exception):
    """A recoverable delivery failure the agent can report and retry."""


class PrinterTransport:
    """Deliver an ESC/POS byte stream to a physical printer."""

    name: str = "abstract"

    def send(self, data: bytes, config: dict | None) -> None:  # pragma: no cover
        raise NotImplementedError


class NetworkTransport(PrinterTransport):
    """Wi-Fi/LAN printer over raw TCP port 9100 (ESC/POS socket)."""

    name = "network"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def send(self, data: bytes, config: dict | None) -> None:
        if not config:
            raise TransportError("printer has no network config")
        host = config.get("host")
        port = int(config.get("port", 9100))
        if not host:
            raise TransportError("printer network config is missing a host")
        try:
            with socket.create_connection((host, port), timeout=self.timeout) as sock:
                sock.sendall(data)
        except OSError as exc:
            raise TransportError(f"cannot reach printer at {host}:{port}") from exc


class BluetoothTransport(PrinterTransport):
    """Placeholder for a dedicated Bluetooth host (e.g. an Android gateway).

    Not implemented — kept so the queue/renderer stay transport-agnostic. A real
    device test is required before this is advertised as supported.
    """

    name = "bluetooth"

    def send(self, data: bytes, config: dict | None) -> None:
        raise TransportError(
            "bluetooth transport is not implemented; use a compatible print host"
        )


_TRANSPORTS: dict[str, type[PrinterTransport]] = {
    NetworkTransport.name: NetworkTransport,
    BluetoothTransport.name: BluetoothTransport,
}


def transport_for(name: str) -> PrinterTransport:
    """Instantiate the transport for a printer's declared transport type."""
    cls = _TRANSPORTS.get(name)
    if cls is None:
        raise TransportError(f"unsupported printer transport: {name}")
    return cls()


@dataclass
class SimulatedPrinter(PrinterTransport):
    """In-test transport that records bytes instead of touching hardware.

    Used by the simulator and the test-suite to prove the raster bytes are
    well-formed without a physical device. ``sink`` receives the byte stream;
    ``fail_next``/``disconnect_next`` model hardware faults.
    """

    sink: list[bytes] | None = None
    fail_next: bool = False
    disconnect_next: bool = False
    name: str = "network"

    def send(self, data: bytes, config: dict | None) -> None:
        if self.disconnect_next:
            self.disconnect_next = False
            raise TransportError("simulated disconnect")
        if self.fail_next:
            self.fail_next = False
            raise TransportError("simulated device error")
        if self.sink is not None:
            self.sink.append(data)

