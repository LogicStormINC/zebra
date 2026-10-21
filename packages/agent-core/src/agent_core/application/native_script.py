"""Invoke fixed read-only scripts; committed receipts precede result use."""

from collections.abc import Callable
from threading import BoundedSemaphore
from uuid import UUID, uuid5

from agent_core.domain.native_script import MAX_SCRIPT_INPUT_BYTES, NativeScript
from agent_core.domain.native_script_protocol import ScriptRunResult
from agent_core.domain.native_script_receipt import (
    NativeScriptEvent,
    fold_native_script,
    script_bytes_digest,
)
from agent_core.domain.runtime_bundle_json import (
    canonical_json_bytes,
    json_digest,
    load_bundle_json,
)
from agent_core.domain.script_bundle import ScriptBinding
from agent_core.ports.native_script import NativeScriptJournalPort, NativeScriptRunnerPort

_INVOCATION_NAMESPACE = UUID("86c640ad-3b6a-4cd6-b967-3c77fbc39361")


class NativeScriptUnavailable(RuntimeError):
    pass


class NativeScriptReceiptUncertain(RuntimeError):
    """The event transaction may have committed; recovery must read canonical facts."""


class NativeScriptInvocationService:
    def __init__(
        self,
        *,
        task_id: str,
        snapshot_digest: str,
        owner_fence: str,
        journal: NativeScriptJournalPort,
        authorize: Callable[[ScriptBinding], NativeScript],
        runner: Callable[[], NativeScriptRunnerPort],
    ) -> None:
        self.task_id, self.snapshot_digest, self.owner_fence = task_id, snapshot_digest, owner_fence
        self._journal, self._authorize, self._runner = journal, authorize, runner
        self._slot = BoundedSemaphore(1)

    def invoke(
        self, binding: ScriptBinding, arguments: dict[str, object], *, logical_id: str
    ) -> ScriptRunResult:
        binding.manifest.input.validate_record(arguments)
        if not logical_id or len(logical_id) > 512:
            raise ValueError("invalid logical script invocation")
        binding_digest = json_digest(binding.model_dump(mode="json"))
        identity = json_digest(
            {
                "task_id": self.task_id,
                "snapshot": self.snapshot_digest,
                "binding": binding_digest,
                "logical_id": logical_id,
                "arguments": arguments,
            }
        )
        invocation_id = str(uuid5(_INVOCATION_NAMESPACE, identity))
        raw = canonical_json_bytes(
            {
                "abi": binding.manifest.abi,
                "invocation_id": invocation_id,
                "manifest_digest": binding.manifest.digest,
                "arguments": arguments,
            }
        )
        if len(raw) > MAX_SCRIPT_INPUT_BYTES:
            raise NativeScriptUnavailable("NATIVE_SCRIPT_INPUT_LIMIT")
        base = {
            "schema_version": "cloud-agent.native-script-event/1",
            "invocation_id": invocation_id,
            "task_id": self.task_id,
            "snapshot_digest": self.snapshot_digest,
            "binding_digest": binding_digest,
            "input_digest": script_bytes_digest(raw),
            "owner_fence": self.owner_fence,
        }

        def authorize() -> NativeScript:
            script = self._authorize(binding)
            if script.manifest != binding.manifest:
                raise NativeScriptUnavailable("NATIVE_SCRIPT_SOURCE_DRIFT")
            return script

        if not self._slot.acquire(blocking=False):
            raise NativeScriptUnavailable("NATIVE_SCRIPT_BUSY")
        try:
            script = authorize()
            history = self._journal.read(invocation_id)
            prior = fold_native_script(history)
            if prior is not None and prior.identity != (
                invocation_id,
                self.task_id,
                self.snapshot_digest,
                binding_digest,
                base["input_digest"],
            ):
                raise NativeScriptUnavailable("NATIVE_SCRIPT_RECEIPT_CONFLICT")
            if prior is not None and prior.phase == "completed":
                result = prior.result()
                if result.observation.manifest_digest != binding.manifest.digest:
                    raise NativeScriptUnavailable("NATIVE_SCRIPT_RECEIPT_CONFLICT")
                if result.output_json is not None:
                    binding.manifest.output.validate_record(load_bundle_json(result.output_json))
                authorize()
                return result
            if prior is not None and (
                prior.owner_fence == self.owner_fence or prior.execution_attempt >= 3
            ):
                raise NativeScriptUnavailable("NATIVE_SCRIPT_UNRESOLVED_INTENT")
            intent = NativeScriptEvent.model_validate(
                base
                | {
                    "phase": "started",
                    "execution_attempt": 1 if prior is None else prior.execution_attempt + 1,
                }
            )
            authorize()
            self._journal.append(intent)

            def check() -> None:
                authorize()

            result = self._runner().run(script, raw, cancellation_check=check)
            authorize()
            if (
                result.observation.invocation_id != invocation_id
                or result.observation.manifest_digest != binding.manifest.digest
                or result.observation.input_digest != base["input_digest"]
            ):
                raise NativeScriptUnavailable("NATIVE_SCRIPT_RUNNER_RECEIPT_CONFLICT")
            if result.output_json is not None:
                binding.manifest.output.validate_record(load_bundle_json(result.output_json))
            completed = NativeScriptEvent.model_validate(
                intent.model_dump()
                | {
                    "phase": "completed",
                    "observation": result.observation,
                    "output_json": None
                    if result.output_json is None
                    else result.output_json.decode("utf-8"),
                }
            )
            self._journal.append(completed)
            authorize()
            return result
        finally:
            self._slot.release()
