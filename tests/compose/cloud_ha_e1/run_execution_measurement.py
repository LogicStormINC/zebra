"""Run E1 preparation before execution, using one interpreter and checked exits."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", required=True, type=Path)
    parser.add_argument("--execute", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    for script in (args.prepare, args.execute):
        if not script.is_file():
            parser.error(f"script not found: {script}")
    if not args.evidence.is_dir():
        parser.error("expected an existing isolated evidence directory")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import httpx; from cryptography.hazmat.primitives.ciphers.aead import AESGCM",
        ],
        check=True,
    )
    for script in (args.prepare, args.execute):
        subprocess.run(
            [sys.executable, str(script.resolve()), str(args.evidence.resolve())], check=True
        )


if __name__ == "__main__":
    main()
