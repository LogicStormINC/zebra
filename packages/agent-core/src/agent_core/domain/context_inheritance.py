"""Bounded, tamper-evident Context transferred from a parent to a child Task."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryType

MAX_DELEGATED_CONTEXT_ITEMS = 24
MAX_DELEGATED_CONTEXT_ITEM_CHARS = 8_192
MAX_DELEGATED_CONTEXT_CHARS = 32_768
MAX_DELEGATED_CONTEXT_OMISSIONS = 32
MAX_DELEGATED_CONTEXT_OMISSION_CHARS = 128
StrictMemoryRevision = Annotated[int, Field(ge=1, strict=True)]
REQUIRED_CONTEXT_OMISSIONS = frozenset(
    {
        "credentials",
        "hidden_reasoning",
        "history_outside_bounded_tail",
        "provider_private_continuation",
        "raw_tool_outputs",
    }
)


class ContextInheritanceMode(StrEnum):
    FRESH = "fresh"
    CAPSULE = "capsule"
    FORK_TAIL = "fork_tail"
    RESUME = "resume"


class DelegatedContextItem(BaseModel):
    """One source-attributed prompt-data item; never executable authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["capsule", "history", "memory"]
    locator: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=MAX_DELEGATED_CONTEXT_ITEM_CHARS)
    source_sequence: int | None = Field(default=None, ge=0, strict=True)
    memory_type: MemoryType | None = None

    @field_validator("locator", "content")
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("delegated Context text must not be blank")
        return value

    @model_validator(mode="after")
    def require_kind_shape(self) -> Self:
        if (self.source_sequence is not None) != (self.kind == "history"):
            raise ValueError("only delegated history carries source_sequence")
        if (self.memory_type is not None) != (self.kind == "memory"):
            raise ValueError("only delegated Memory carries memory_type")
        return self


class DelegatedContextSnapshot(BaseModel):
    """Durable child bootstrap input derived from one trusted read generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["delegated-context/1"] = "delegated-context/1"
    mode: ContextInheritanceMode
    source_session_id: SessionId
    source_session_revision: int = Field(ge=0, strict=True)
    active_capsule_id: str | None = Field(default=None, max_length=255)
    memory_revisions: tuple[tuple[str, StrictMemoryRevision], ...] = Field(
        default=(), max_length=MAX_DELEGATED_CONTEXT_ITEMS
    )
    items: tuple[DelegatedContextItem, ...] = Field(
        default=(), max_length=MAX_DELEGATED_CONTEXT_ITEMS
    )
    known_omissions: tuple[str, ...] = Field(max_length=MAX_DELEGATED_CONTEXT_OMISSIONS)
    created_at: datetime
    checksum: str

    @field_validator("active_capsule_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("delegated Context identifiers must not be blank")
        return value

    @field_validator("known_omissions")
    @classmethod
    def normalize_omissions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if (
            any(
                not value or len(value) > MAX_DELEGATED_CONTEXT_OMISSION_CHARS
                for value in normalized
            )
            or len(set(normalized)) != len(normalized)
            or tuple(sorted(normalized)) != normalized
        ):
            raise ValueError("delegated Context omissions must be unique non-blank values")
        return normalized

    @field_validator("checksum")
    @classmethod
    def require_checksum(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("delegated Context checksum must be a sha256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("delegated Context created_at must be timezone-aware")
        if not REQUIRED_CONTEXT_OMISSIONS.issubset(self.known_omissions):
            raise ValueError("delegated Context known omissions are incomplete")
        if tuple(sorted(self.memory_revisions)) != self.memory_revisions:
            raise ValueError("delegated Context memory revisions must be sorted")
        try:
            canonical_memory_ids = tuple(
                str(UUID(memory_id.strip())) for memory_id, _ in self.memory_revisions
            )
        except (AttributeError, ValueError) as exc:
            raise ValueError("delegated Context memory revisions are invalid") from exc
        if canonical_memory_ids != tuple(
            memory_id for memory_id, _ in self.memory_revisions
        ) or len(set(canonical_memory_ids)) != len(canonical_memory_ids):
            raise ValueError("delegated Context memory revisions are invalid")
        if len({item.locator for item in self.items}) != len(self.items):
            raise ValueError("delegated Context item locators must be unique")
        if sum(len(item.content) for item in self.items) > MAX_DELEGATED_CONTEXT_CHARS:
            raise ValueError("delegated Context exceeds its character budget")
        capsule_items = tuple(item for item in self.items if item.kind == "capsule")
        history_items = tuple(item for item in self.items if item.kind == "history")
        memory_items = tuple(item for item in self.items if item.kind == "memory")
        kinds = {item.kind for item in self.items}
        if self.mode is ContextInheritanceMode.FRESH and (
            self.items or self.active_capsule_id is not None or self.memory_revisions
        ):
            raise ValueError("fresh mode must not inherit Context items")
        if self.mode is ContextInheritanceMode.CAPSULE and (
            len(self.items) != 1
            or kinds != {"capsule"}
            or self.active_capsule_id is None
            or self.memory_revisions
        ):
            raise ValueError("capsule mode requires only one active Capsule source")
        if self.mode is ContextInheritanceMode.FORK_TAIL and (
            not self.items
            or kinds != {"history"}
            or self.active_capsule_id is not None
            or self.memory_revisions
        ):
            raise ValueError("fork_tail mode requires only bounded History sources")
        if self.mode is ContextInheritanceMode.RESUME and (
            not self.items or not kinds.issubset({"capsule", "history", "memory"})
        ):
            raise ValueError("resume mode requires bounded continuity sources")
        expected_capsules = (
            {f"context-capsule://{self.active_capsule_id}"}
            if self.active_capsule_id is not None
            else set()
        )
        if {item.locator for item in capsule_items} != expected_capsules:
            raise ValueError("delegated Context Capsule locator is inconsistent")
        history_sequences = tuple(
            item.source_sequence for item in history_items if item.source_sequence is not None
        )
        if (
            len(history_sequences) != len(history_items)
            or history_sequences != tuple(sorted(history_sequences))
            or any(
                item.locator != f"session-event://{self.source_session_id}/{item.source_sequence}"
                for item in history_items
            )
        ):
            raise ValueError("delegated Context History locators are inconsistent")
        expected_memories = {
            f"confirmed-memory://{memory_id}@{revision}"
            for memory_id, revision in self.memory_revisions
        }
        if {item.locator for item in memory_items} != expected_memories:
            raise ValueError("delegated Context Memory locators are inconsistent")
        if self.checksum != self.expected_checksum():
            raise ValueError("delegated Context checksum does not match its content")
        return self

    @classmethod
    def create(
        cls,
        *,
        mode: ContextInheritanceMode,
        source_session_id: SessionId,
        source_session_revision: int,
        active_capsule_id: str | None = None,
        memory_revisions: tuple[tuple[str, int], ...] = (),
        items: tuple[DelegatedContextItem, ...] = (),
        known_omissions: tuple[str, ...],
        created_at: datetime,
    ) -> Self:
        payload = {
            "mode": mode,
            "source_session_id": source_session_id,
            "source_session_revision": source_session_revision,
            "active_capsule_id": active_capsule_id,
            "memory_revisions": memory_revisions,
            "items": items,
            "known_omissions": known_omissions,
            "created_at": created_at,
        }
        unsigned = cls.model_construct(
            mode=mode,
            source_session_id=source_session_id,
            source_session_revision=source_session_revision,
            active_capsule_id=active_capsule_id,
            memory_revisions=memory_revisions,
            items=items,
            known_omissions=known_omissions,
            created_at=created_at,
            checksum="",
        )
        return cls.model_validate({**payload, "checksum": unsigned.expected_checksum()})

    def expected_checksum(self) -> str:
        payload = self.model_dump(mode="json", exclude={"checksum"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
