"""Offline validation only: no publication, asset resolution or Runtime execution."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from agent_core.domain.runtime_bundle import (
    MAX_BUNDLE_BYTES,
    RuntimeDomains,
    builtin_component_pin,
    parse_runtime_bundle,
    require_bundle_compatibility,
    runtime_bundle_catalog,
    runtime_bundle_json_schema,
)


def _read_regular(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("regular input required")
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("input too large")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path)
    group.add_argument("--schema", action="store_true")
    group.add_argument("--catalog", action="store_true")
    arguments = parser.parse_args()
    if arguments.schema:
        output = runtime_bundle_json_schema()
    elif arguments.catalog:
        output = runtime_bundle_catalog()
    else:
        try:
            envelope = parse_runtime_bundle(_read_regular(arguments.input))
            require_bundle_compatibility(
                envelope,
                supported_bundle_abis=frozenset({"cloud-agent.bundle/1"}),
                supported_component_digests=frozenset(
                    builtin_component_pin(domain).digest for domain in RuntimeDomains.model_fields
                ),
            )
            output = {
                "contract_version": "cloud-agent.bundle-validation/1",
                "bundle_digest": envelope.bundle_digest,
                "catalog_digest": envelope.manifest.catalog_digest,
                "validation_only": True,
                "execution_supported": False,
            }
        except (OSError, ValueError, TypeError, RecursionError):
            # Pydantic and JSON errors may contain instructions or private input.
            print(json.dumps({"error": {"code": "INVALID_BUNDLE"}}))
            return 2
    print(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
