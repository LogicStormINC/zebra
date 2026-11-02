"""Pre-release check: python3 deploy/check_auth_release.py --override /path/to/override.json.

Read-only; no Frappe login, grant creation, HTTP call, Task or Controller operation.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

TARGET = "/home/frappe/frappe-bench/apps/zebra_erpnext/zebra_erpnext/client.py"


def check_overlay(source, override):
    for service, config in override.get("services", {}).items():
        for volume in config.get("volumes", []):
            if isinstance(volume, str):
                parts = volume.split(":")
                host, target = parts[:2] if len(parts) >= 2 else ("", "")
            else:
                host, target = volume.get("source", ""), volume.get("target", "")
            for name in ("client.py", "api.py", "business.py"):
                destination = PurePosixPath(TARGET).with_name(name)
                if not target or not destination.is_relative_to(PurePosixPath(target)):
                    continue
                path = Path(host) / str(destination.relative_to(PurePosixPath(target)))
                expected = hashlib.sha256((source / "zebra_erpnext" / name).read_bytes()).digest()
                if not path.is_absolute() or hashlib.sha256(path.read_bytes()).digest() != expected:
                    raise ValueError(f"{service}: stale {name} mount would shadow candidate source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--override", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    for test in [
        "test_client_checks.py",
        "test_legacy_manifest_checks.py",
        "test_ingress_prepare_checks.py",
        "test_origin_bootstrap_checks.py",
        "test_auth_release_checks.py",
    ]:
        subprocess.run([sys.executable, str(source / "tests" / test)], check=True)
    if args.override:
        check_overlay(source, json.loads(args.override.read_text()))
    print("PASS source authentication contracts and supplied release override")


if __name__ == "__main__":
    main()
