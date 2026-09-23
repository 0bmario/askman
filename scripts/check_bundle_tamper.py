#!/usr/bin/env python3
"""Exercise the public CLI boundary against same-size bundle tampering.

The command primes a temporary bundle copy so its validation evidence exists,
mutates one artifact byte while restoring its mtime, then requires the next
public query to fail closed on the component digest.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_query(
    binary: Path, bundle: Path, query: list[str], ort_lib: Path | None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if ort_lib is not None:
        environment["DYLD_LIBRARY_PATH"] = str(ort_lib)
    return subprocess.run(
        [str(binary), "--json", "--bundle", str(bundle), *query],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--query", nargs="+", required=True)
    parser.add_argument("--ort-lib", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="askman-tamper-") as temporary:
        bundle = Path(temporary) / "matching-bundle"
        shutil.copytree(args.bundle, bundle)
        primed = run_query(args.binary, bundle, args.query, args.ort_lib)
        if primed.returncode != 0:
            raise SystemExit(
                f"prime query failed with status {primed.returncode}: {primed.stderr.strip()}"
            )

        stamp_path = bundle.parent / ".matching-bundle.stamp-v2.json"
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        stamp["binding_sha256"] = "0" * 64
        stamp_path.write_text(json.dumps(stamp), encoding="utf-8")
        forged = run_query(args.binary, bundle, args.query, args.ort_lib)
        if forged.returncode != 0:
            raise SystemExit(
                f"forged evidence rejected an otherwise valid bundle: {forged.stderr.strip()}"
            )
        refreshed = json.loads(stamp_path.read_text(encoding="utf-8"))
        if refreshed["binding_sha256"] == "0" * 64:
            raise SystemExit("forged validation evidence was reused")

        artifact = bundle / "matching.db"
        metadata = artifact.stat()
        with artifact.open("r+b") as file:
            original = file.read(1)
            if len(original) != 1:
                raise SystemExit("matching artifact is empty")
            file.seek(0)
            file.write(bytes([original[0] ^ 0x01]))
            file.flush()
            os.fsync(file.fileno())
        os.utime(artifact, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

        tampered = run_query(args.binary, bundle, args.query, args.ort_lib)
        combined = f"{tampered.stdout}\n{tampered.stderr}"
        if tampered.returncode == 0:
            raise SystemExit("tampered bundle query unexpectedly succeeded")
        if "digest mismatch" not in combined:
            raise SystemExit(
                "tampered bundle failed without a component digest error:\n" + combined
            )

    print("public bundle tamper regression passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
