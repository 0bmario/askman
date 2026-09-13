#!/usr/bin/env python3
"""Fail unless the process is prevented from opening a network socket."""

import errno
import socket
import sys


def main() -> int:
    allow_unreachable = sys.argv[1:] == ["--allow-unreachable"]
    blocked_errors = {errno.EPERM, errno.EACCES}
    if allow_unreachable:
        blocked_errors.update(
            {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED}
        )

    # A loopback connection avoids depending on an external service. The
    # offline runner must deny the connect itself, rather than merely relying
    # on DNS or an unavailable remote host.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        try:
            sock.connect(("127.0.0.1", 65534))
        except OSError as error:
            # sandbox-exec rejects connect(2) with EPERM/EACCES. An empty
            # Linux network namespace has no usable route and reports one of
            # the unreachable/refused errors instead.
            if error.errno in blocked_errors:
                print(f"network denied: errno={error.errno}")
                return 0
            print(f"network was not denied by the runner: {error}")
            return 1

    print("network was not denied by the runner: connection succeeded")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
