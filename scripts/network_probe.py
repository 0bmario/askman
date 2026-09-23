#!/usr/bin/env python3
"""Provide a local TCP probe for OS-enforced outbound-denial checks."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import socketserver
import threading
import time
from pathlib import Path
from urllib.request import urlopen


class ProbeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: Path):
        self.state = state
        self.connections = 0
        super().__init__(address, ProbeHandler)
        self._write_state()

    def _write_state(self) -> None:
        self.state.write_text(
            json.dumps(
                {
                    "host": self.server_address[0],
                    "port": self.server_address[1],
                    "connections": self.connections,
                    "pid": os.getpid(),
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def record_connection(self) -> None:
        self.connections += 1
        self._write_state()


class ProbeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.record_connection()  # type: ignore[attr-defined]
        try:
            self.request.recv(4096)
            self.request.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass


def serve(state: Path) -> int:
    state.parent.mkdir(parents=True, exist_ok=True)
    server = ProbeServer(("127.0.0.1", 0), state)
    def stop(*_signals: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0


def request(url: str, timeout: float) -> int:
    try:
        with urlopen(url, timeout=timeout) as response:
            response.read(32)
    except OSError as error:
        print(f"network probe denied: {error}")
        return 1
    print("network probe unexpectedly connected")
    return 0


def assert_denied(state: Path, wait: float) -> int:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if state.is_file():
            break
        time.sleep(0.05)
    if not state.is_file():
        raise SystemExit(f"network probe state was not created: {state}")
    payload = json.loads(state.read_text(encoding="utf-8"))
    pid = payload.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except OSError as error:
            raise SystemExit(f"network probe server is not alive: {pid}") from error
    if payload.get("connections") != 0:
        raise SystemExit(f"network denial probe connected: {payload}")
    print("network denial probe observed zero accepted connections")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    server_parser = subparsers.add_parser("server")
    server_parser.add_argument("--state", type=Path, required=True)
    request_parser = subparsers.add_parser("request")
    request_parser.add_argument("--url", required=True)
    request_parser.add_argument("--timeout", type=float, default=3.0)
    assert_parser = subparsers.add_parser("assert-denied")
    assert_parser.add_argument("--state", type=Path, required=True)
    assert_parser.add_argument("--wait", type=float, default=0.5)
    args = parser.parse_args()
    if args.command == "server":
        return serve(args.state)
    if args.command == "request":
        return request(args.url, args.timeout)
    return assert_denied(args.state, args.wait)


if __name__ == "__main__":
    raise SystemExit(main())
