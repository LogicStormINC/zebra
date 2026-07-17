from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from agent_core.domain.messages import SessionMessage

TOMBSTONE_MARKER = "[Zebra tool-result tombstone]"
PROJECTED_CALL_MARKER = "[Zebra projected tool call]"
LEDGER_MARKER = "[Zebra protected instruction ledger]"


class ProtectedInstructionKind(StrEnum):
    SYSTEM_RULE = "system_rule"
    USER_OBJECTIVE = "user_objective"
    USER_CONSTRAINT = "user_constraint"


@dataclass(frozen=True)
class ProtectedInstruction:
    kind: ProtectedInstructionKind
    content: str
    source_message_id: str
    checksum: str


@dataclass(frozen=True)
class ProtectedInstructionLedger:
    entries: tuple[ProtectedInstruction, ...]

    def render(self) -> str:
        payload = [
            {
                "checksum": entry.checksum,
                "content": entry.content,
                "kind": entry.kind.value,
                "source_message_id": entry.source_message_id,
            }
            for entry in self.entries
        ]
        return f"{LEDGER_MARKER}\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


@dataclass(frozen=True)
class ToolResultTombstone:
    tool_name: str
    call_id: str
    status: str
    artifact_uri: str
    checksum: str
    original_characters: int
    provenance_source: str = "tool_trace"

    def render(self) -> str:
        return f"{TOMBSTONE_MARKER}\n{json.dumps(self.__dict__, sort_keys=True)}"

    @classmethod
    def parse(cls, content: str) -> ToolResultTombstone | None:
        if not content.startswith(f"{TOMBSTONE_MARKER}\n"):
            return None
        try:
            payload = json.loads(content.split("\n", 1)[1])
            return cls(**payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


@dataclass(frozen=True)
class FoldedToolExchange:
    assistant: SessionMessage
    results: tuple[SessionMessage, ...]
    tombstones: tuple[ToolResultTombstone, ...]

    @property
    def call_ids(self) -> frozenset[str]:
        return frozenset(tombstone.call_id for tombstone in self.tombstones)


@dataclass(frozen=True)
class ActiveContextProjection:
    messages: tuple[SessionMessage, ...]
    protected_ledger: ProtectedInstructionLedger
    folded_exchanges: tuple[FoldedToolExchange, ...]
    content_versions: tuple[tuple[str, str], ...]
