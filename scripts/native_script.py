"""Validate, or explicitly exercise, a producer-owned native script artifact."""

import argparse
import json
import sys
from pathlib import Path

from agent_core.domain.native_script import (
    MAX_SCRIPT_BYTES,
    MAX_SCRIPT_INPUT_BYTES,
    parse_native_script,
)
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.ports.runtime import RuntimeClass, RuntimeLimits, SandboxSpec
from agent_runtime.adapters.os_sandbox import OsSandboxRuntime
from agent_runtime.adapters.os_sandbox_platform import os_sandbox_engine
from agent_runtime.native_script import NativeScriptRunner


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("artifact_size_limit")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--invocation", type=Path)
    parser.add_argument("--run-os-sandbox", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    try:
        script = parse_native_script(
            _read(args.manifest, MAX_SCRIPT_BYTES), _read(args.source, MAX_SCRIPT_BYTES)
        )
        if not args.run_os_sandbox:
            print(
                json.dumps(
                    {
                        "abi": script.manifest.abi,
                        "manifest_digest": script.manifest.digest,
                        "source_digest": script.manifest.source_digest,
                    }
                )
            )
            return 0
        if args.invocation is None:
            raise ValueError("invocation_required")
        raw = _read(args.invocation, MAX_SCRIPT_INPUT_BYTES)
        python = Path(args.python).resolve(strict=True)
        # Only the interpreter installation is readable; no business workspace mount.
        workspace = str(python.parent.parent)
        spec = SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="development-os-sandbox",
            engine=os_sandbox_engine(),
            workspace_root=workspace,
            workspace_writable=False,
            network_profile="none",
            limits=RuntimeLimits(max_execution_seconds=30, max_output_bytes=32_768),
        )
        result = NativeScriptRunner(OsSandboxRuntime(spec), spec, python=str(python)).run(
            script, raw
        )
        print(
            json.dumps(
                {
                    "observation": result.observation.model_dump(mode="json"),
                    "output": None
                    if result.output_json is None
                    else load_bundle_json(result.output_json),
                }
            )
        )
        return 0 if result.observation.status == "succeeded" else 1
    except (OSError, ValueError, RuntimeError):
        # Do not expose source, invocation data, command argv or raw child stderr.
        print("native_script_refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
