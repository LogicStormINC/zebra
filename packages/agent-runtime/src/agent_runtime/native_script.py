"""Opt-in one-shot transforms using the existing read-only sandbox boundary."""

import sys
from collections.abc import Callable
from hashlib import sha256
from pathlib import PurePosixPath
from threading import BoundedSemaphore
from typing import Literal

from agent_core.domain.native_script import (
    MAX_SCRIPT_INPUT_BYTES,
    MAX_SCRIPT_OUTPUT_BYTES,
    NativeScript,
    NativeScriptError,
)
from agent_core.domain.native_script_protocol import (
    ScriptInvocation,
    ScriptObservation,
    ScriptResponse,
    ScriptRunResult,
)
from agent_core.domain.runtime_bundle_json import canonical_json_bytes, load_bundle_json
from agent_core.ports.runtime import (
    RuntimeClass,
    RuntimeExecutionRequest,
    RuntimePort,
    SandboxSpec,
)

from agent_runtime.native_script_bootstrap import BOOTSTRAP


class NativeScriptRunner:
    """Own a dedicated RuntimePort instance; never share its active handle.

    ponytail: one in-flight invocation per runner protects mutable RuntimePort
    handles. Worker integration needs its existing durable lease and admission
    budgets; this semaphore is only local backpressure, not distributed authority.
    """

    def __init__(self, runtime: RuntimePort, spec: SandboxSpec, *, python: str) -> None:
        if (
            spec.runtime_class
            not in {RuntimeClass.OS_SANDBOX, RuntimeClass.OCI_ROOTLESS, RuntimeClass.GVISOR}
            or spec.workspace_writable
            or spec.network_profile != "none"
            or spec.limits.max_output_bytes > MAX_SCRIPT_OUTPUT_BYTES
            or spec.limits.max_execution_seconds > 30
            or not PurePosixPath(python).is_absolute()
            or "\x00" in python
        ):
            raise NativeScriptError("unsafe_script_runtime")
        self._runtime, self._spec, self._python = runtime, spec, python
        self._slot = BoundedSemaphore(1)

    def run(
        self,
        script: NativeScript,
        raw_invocation: bytes,
        *,
        cancellation_check: Callable[[], None] | None = None,
    ) -> ScriptRunResult:
        # Recheck immutable identities at the boundary, even for a hand-built value.
        NativeScript(script.manifest, script.source)
        try:
            if type(raw_invocation) is not bytes or len(raw_invocation) > MAX_SCRIPT_INPUT_BYTES:
                raise ValueError("invocation size")
            value = load_bundle_json(raw_invocation)
            invocation = ScriptInvocation.model_validate(value)
            script.manifest.input.validate_record(value["arguments"])
            if invocation.manifest_digest != script.manifest.digest:
                raise ValueError("manifest digest")
            if script.manifest.max_output_bytes > self._spec.limits.max_output_bytes:
                raise ValueError("output budget")
            if script.manifest.timeout_seconds > self._spec.limits.max_execution_seconds:
                raise ValueError("time budget")
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise NativeScriptError("invalid_invocation") from None
        if not self._slot.acquire(blocking=False):
            raise NativeScriptError("script_runner_busy")
        handle = None
        check = cancellation_check or (lambda: None)
        try:
            check()
            capabilities = self._runtime.inspect_capabilities()
            if not capabilities.available or capabilities.runtime_class != self._spec.runtime_class:
                raise NativeScriptError("script_runtime_unavailable")
            handle = self._runtime.provision(spec=self._spec)
            check()
            authority = handle.authority
            if (
                authority is None
                or authority.spec_digest != self._spec.digest
                or authority.runtime_class != self._spec.runtime_class
                or authority.workspace_writable
                or authority.network_enforcement
                not in {"os-sandbox-network-deny", "container-network-none"}
            ):
                raise NativeScriptError("script_runtime_authority_mismatch")
            result = self._runtime.execute(
                RuntimeExecutionRequest(
                    command=(
                        self._python,
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        BOOTSTRAP,
                    ),
                    stdin_input=canonical_json_bytes(
                        {"source": script.source.decode("utf-8"), "invocation": value}
                    ),
                    cancellation_check=cancellation_check,
                    cwd=self._spec.workspace_root,
                    timeout_seconds=script.manifest.timeout_seconds,
                )
            )
            check()
            reason: Literal["ok", "timeout", "process_failed", "output_limit", "invalid_response"]
            output: bytes | None = None
            if result.timed_out:
                reason = "timeout"
            elif (
                result.stdout_truncated
                or result.stderr_truncated
                or (len(result.stdout.encode("utf-8")) > script.manifest.max_output_bytes)
            ):
                reason = "output_limit"
            elif not result.succeeded or result.stderr:
                reason = "process_failed"
            else:
                try:
                    frame = load_bundle_json(result.stdout.encode("utf-8"))
                    response = ScriptResponse.model_validate(frame)
                    if (
                        response.invocation_id != invocation.invocation_id
                        or response.manifest_digest != script.manifest.digest
                    ):
                        raise ValueError("response binding")
                    script.manifest.output.validate_record(frame["output"])
                    output = canonical_json_bytes(frame["output"])
                    reason = "ok"
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                    reason = "invalid_response"
            return ScriptRunResult(
                ScriptObservation(
                    abi=invocation.abi,
                    invocation_id=invocation.invocation_id,
                    manifest_digest=script.manifest.digest,
                    input_digest="sha256:" + sha256(raw_invocation).hexdigest(),
                    runtime_spec_digest=self._spec.digest,
                    status="succeeded" if reason == "ok" else "failed",
                    reason=reason,
                    output_digest=None
                    if output is None
                    else "sha256:" + sha256(output).hexdigest(),
                ),
                output,
            )
        finally:
            try:
                if handle is not None:
                    original = sys.exception()
                    try:
                        self._runtime.destroy(handle)
                    except Exception as cleanup:
                        if original is None:
                            raise
                        original.add_note(
                            f"native runtime cleanup failed: {type(cleanup).__name__}"
                        )
            finally:
                self._slot.release()
