from collections.abc import Callable
from typing import Protocol

from agent_core.domain.native_script import NativeScript
from agent_core.domain.native_script_protocol import ScriptRunResult
from agent_core.domain.native_script_receipt import NativeScriptEvent


class NativeScriptJournalPort(Protocol):
    def read(self, invocation_id: str) -> tuple[NativeScriptEvent, ...]: ...

    def append(self, event: NativeScriptEvent) -> None: ...


class NativeScriptRunnerPort(Protocol):
    def run(
        self,
        script: NativeScript,
        raw_invocation: bytes,
        *,
        cancellation_check: Callable[[], None] | None = None,
    ) -> ScriptRunResult: ...
