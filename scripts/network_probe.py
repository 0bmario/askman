#!/usr/bin/env python3
"""Provide local and external probes for OS-enforced outbound-denial checks."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import socketserver
import ssl
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen


EXPECTED_EXTERNAL_URL = "https://github.com/"
WINDOWS_FIREWALL_ERROR = "windows-firewall"


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


def _write_external_state(
    state: Path,
    *,
    url: str,
    baseline_succeeded: bool,
    nonce: str | None,
    accepted: bool,
    denied: bool,
    error: BaseException | None = None,
    error_classification: str,
    http_status: int | None = None,
) -> None:
    state.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "mode": "external",
        "url": url,
        "nonce": nonce,
        "baseline_succeeded": baseline_succeeded,
        "denied": denied,
        "accepted": accepted,
        "connections": 0,
        "error_classification": error_classification,
    }
    if error is not None:
        payload["error"] = str(error)
    if http_status is not None:
        payload["http_status"] = http_status
    state.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _error_candidates(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        reason = getattr(current, "reason", None)
        current = reason if isinstance(reason, BaseException) else None


def _classify_error(error: BaseException) -> str:
    candidates = tuple(_error_candidates(error))
    if any(getattr(candidate, "winerror", None) == 10013 for candidate in candidates):
        return WINDOWS_FIREWALL_ERROR
    if any(isinstance(candidate, (TimeoutError, socket.timeout)) for candidate in candidates):
        return "timeout"
    if any(isinstance(candidate, socket.gaierror) for candidate in candidates):
        return "dns"
    if any(isinstance(candidate, ssl.SSLError) for candidate in candidates):
        return "tls"
    if any("proxy" in str(candidate).lower() for candidate in candidates):
        return "proxy"
    if isinstance(error, ValueError):
        return "invalid-url"
    return "network-error"


def request(
    url: str,
    timeout: float,
    *,
    state: Path | None = None,
    baseline_succeeded: bool = False,
    nonce: str | None = None,
) -> int:
    response_received = False
    try:
        with urlopen(url, timeout=timeout) as response:
            response_received = True
            response.read(32)
    except HTTPError as error:
        if state is not None:
            _write_external_state(
                state,
                url=url,
                baseline_succeeded=baseline_succeeded,
                nonce=nonce,
                accepted=True,
                denied=False,
                error=error,
                error_classification="http-response",
                http_status=error.code,
            )
        error.close()
        print(f"network probe accepted HTTP response: {error.code}")
        return 0
    except (OSError, ValueError) as error:
        if response_received:
            if state is not None:
                _write_external_state(
                    state,
                    url=url,
                    baseline_succeeded=baseline_succeeded,
                    nonce=nonce,
                    accepted=True,
                    denied=False,
                    error=error,
                    error_classification="http-response",
                )
            print(f"network probe accepted HTTP response: {error}")
            return 0
        error_classification = _classify_error(error)
        denied = error_classification == WINDOWS_FIREWALL_ERROR
        if state is not None:
            _write_external_state(
                state,
                url=url,
                baseline_succeeded=baseline_succeeded,
                nonce=nonce,
                accepted=False,
                denied=denied,
                error=error,
                error_classification=error_classification,
            )
        if denied:
            print(f"network probe denied by Windows firewall: {error}")
            return 1
        print(f"network probe failed ({error_classification}): {error}")
        return 1
    if state is not None:
        _write_external_state(
            state,
            url=url,
            baseline_succeeded=baseline_succeeded,
            nonce=nonce,
            accepted=True,
            denied=False,
            error_classification="http-response",
        )
    print("network probe unexpectedly connected")
    return 0


def assert_denied(
    state: Path,
    wait: float,
    *,
    expected_url: str = EXPECTED_EXTERNAL_URL,
    expected_nonce: str | None = None,
) -> int:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if state.is_file():
            break
        time.sleep(0.05)
    if not state.is_file():
        raise SystemExit(f"network probe state was not created: {state}")
    payload = json.loads(state.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"network denial probe state is invalid: {payload}")
    if expected_nonce is not None and payload.get("mode") != "external":
        raise SystemExit(
            f"nonce-bound network denial requires external probe state: {payload}"
        )
    if payload.get("mode") == "external":
        required = {
            "url",
            "nonce",
            "baseline_succeeded",
            "denied",
            "accepted",
            "connections",
            "error_classification",
        }
        try:
            url_value = payload.get("url")
            parsed_url = urlparse(url_value) if isinstance(url_value, str) else None
            hostname = parsed_url.hostname if parsed_url is not None else None
        except ValueError:
            parsed_url = None
            hostname = None
        if (
            not required.issubset(payload)
            or not isinstance(payload.get("url"), str)
            or payload.get("url") != EXPECTED_EXTERNAL_URL
            or payload.get("url") != expected_url
            or not isinstance(payload.get("nonce"), str)
            or not payload.get("nonce")
            or expected_nonce is None
            or payload.get("nonce") != expected_nonce
            or parsed_url is None
            or parsed_url.scheme.lower() != "https"
            or not parsed_url.netloc
            or not hostname
            or payload.get("baseline_succeeded") is not True
            or payload.get("denied") is not True
            or payload.get("accepted") is not False
            or type(payload.get("connections")) is not int
            or payload.get("connections") != 0
            or payload.get("error_classification") != WINDOWS_FIREWALL_ERROR
        ):
            raise SystemExit(f"network denial probe state is invalid: {payload}")
        print("external network denial probe observed a denied connection")
        return 0
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
    request_parser.add_argument("--state", type=Path)
    request_parser.add_argument("--baseline-succeeded", action="store_true")
    request_parser.add_argument("--nonce")
    assert_parser = subparsers.add_parser("assert-denied")
    assert_parser.add_argument("--state", type=Path, required=True)
    assert_parser.add_argument("--wait", type=float, default=0.5)
    assert_parser.add_argument("--expected-url", default=EXPECTED_EXTERNAL_URL)
    assert_parser.add_argument("--expected-nonce")
    args = parser.parse_args()
    if args.command == "server":
        return serve(args.state)
    if args.command == "request":
        return request(
            args.url,
            args.timeout,
            state=args.state,
            baseline_succeeded=args.baseline_succeeded,
            nonce=args.nonce,
        )
    return assert_denied(
        args.state,
        args.wait,
        expected_url=args.expected_url,
        expected_nonce=args.expected_nonce,
    )


if __name__ == "__main__":
    raise SystemExit(main())
