from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_IDENTIFIER = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_VERSION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_REFERENCE = re.compile(r"^(system|skill|eval)://([a-zA-Z][a-zA-Z0-9_-]{0,63})$")
SUPPORTED_MODEL_CAPABILITIES = frozenset({"text", "tools", "image"})
MAX_COMPLETION_REQUIREMENTS = 32


def _normalize_identity(
    value: str,
    *,
    field_name: str,
    pattern: re.Pattern[str],
) -> str:
    if not isinstance(value, str) or any(not character.isprintable() for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    normalized = value.strip()
    if pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must use a safe identifier")
    return normalized


def _normalize_reference(value: str, *, field_name: str, scheme: str) -> str:
    if not isinstance(value, str) or any(not character.isprintable() for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    normalized = value.strip()
    if not normalized.startswith(f"{scheme}://") or _REFERENCE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must use a supported {scheme}:// reference")
    return normalized


class CompletionEvidenceRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    typed_evidence: tuple[str, ...] = ()
    tool_tags: tuple[str, ...] = ()
    validator_outcome: str | None = None
    capability_result: str | None = None

    @field_validator("evidence_id", "validator_outcome", "capability_result")
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("completion evidence text must not be blank")
        return normalized

    @field_validator("typed_evidence", "tool_tags", mode="before")
    @classmethod
    def normalize_evidence_names(cls, value: Sequence[str]) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError("completion evidence names must be a sequence")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("completion evidence names must be non-blank strings")
            item = item.strip()
            if item not in normalized:
                normalized.append(item)
        return tuple(normalized)

    @model_validator(mode="after")
    def require_matcher(self) -> CompletionEvidenceRequirement:
        if not (
            self.typed_evidence
            or self.tool_tags
            or self.validator_outcome
            or self.capability_result
        ):
            raise ValueError("completion evidence requirement must define a typed matcher")
        return self


class CompletionEvidenceContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "1"
    required_evidence: tuple[CompletionEvidenceRequirement, ...] = ()

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != "1":
            raise ValueError("unsupported completion evidence contract version")
        return normalized

    @field_validator("required_evidence")
    @classmethod
    def validate_requirement_count(
        cls, value: tuple[CompletionEvidenceRequirement, ...]
    ) -> tuple[CompletionEvidenceRequirement, ...]:
        if len(value) > MAX_COMPLETION_REQUIREMENTS:
            raise ValueError(
                "completion evidence contract accepts at most "
                f"{MAX_COMPLETION_REQUIREMENTS} requirements"
            )
        ids = [item.evidence_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("completion evidence requirement ids must be unique")
        return value


class AgentDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    version: str
    system_prompt_ref: str | None = None
    skill_refs: tuple[str, ...] = ()
    skill_guidance: tuple[Mapping[str, str], ...] = Field(default_factory=tuple)
    required_model_capabilities: tuple[str, ...] = ()
    capability_policy: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)
    trust_policy: dict[str, Any] = Field(default_factory=dict)
    eval_suite_ref: str | None = None
    resolved_context_digest: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    completion_contract: CompletionEvidenceContract = Field(
        default_factory=CompletionEvidenceContract
    )

    @field_validator("agent_id", "version")
    @classmethod
    def normalize_identity(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_identity(
            value,
            field_name=info.field_name,
            pattern=_IDENTIFIER if info.field_name == "agent_id" else _VERSION,
        )

    @field_validator("system_prompt_ref")
    @classmethod
    def validate_system_prompt_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_reference(value, field_name="system_prompt_ref", scheme="system")

    @field_validator("eval_suite_ref")
    @classmethod
    def validate_eval_suite_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_reference(value, field_name="eval_suite_ref", scheme="eval")

    @field_validator("resolved_context_digest")
    @classmethod
    def validate_resolved_context_digest(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value.strip()) is None:
            raise ValueError("resolved_context_digest must be a lowercase SHA-256 digest")
        return value.strip() if value is not None else None

    @field_validator("skill_guidance", mode="before")
    @classmethod
    def validate_skill_guidance(cls, value: Sequence[object]) -> tuple[Mapping[str, str], ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError("skill_guidance must be a sequence")
        normalized: list[Mapping[str, str]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError("skill_guidance entries must be mappings")
            entry = dict(item)
            name = entry.get("name")
            content = entry.get("content")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("skill_guidance name must be a non-blank string")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("skill_guidance content must be a non-blank string")
            normalized.append({"name": name.strip(), "content": content.strip()})
        return tuple(normalized)

    @field_validator("skill_refs", mode="before")
    @classmethod
    def validate_skill_references(cls, value: Sequence[str]) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError("skill_refs must be a sequence")
        normalized: list[str] = []
        for item in value:
            reference = _normalize_reference(
                item,
                field_name="skill_refs",
                scheme="skill",
            )
            if reference not in normalized:
                normalized.append(reference)
        return tuple(normalized)

    @field_validator("required_model_capabilities", mode="before")
    @classmethod
    def validate_model_capabilities(cls, value: Sequence[str]) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError("required_model_capabilities must be a sequence")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("required model capabilities must be non-blank strings")
            capability = item.strip()
            if capability not in SUPPORTED_MODEL_CAPABILITIES:
                raise ValueError("agent definition requires an unsupported model capability")
            if capability not in normalized:
                normalized.append(capability)
        return tuple(normalized)

    def missing_model_capabilities(self, available: Sequence[str]) -> tuple[str, ...]:
        return tuple(
            capability
            for capability in self.required_model_capabilities
            if capability not in available
        )


def parse_agent_definition(value: object) -> AgentDefinition | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("agent_definition must be an object")
    if "resolved_context_digest" in value:
        raise ValueError("resolved_context_digest is server-generated")
    return AgentDefinition.model_validate(value)


@dataclass(frozen=True)
class AgentDefinitionContext:
    agent_id: str
    version: str
    system_prompt: str | None = None
    skill_guidance: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "agent_id",
            _normalize_identity(
                self.agent_id,
                field_name="agent_id",
                pattern=_IDENTIFIER,
            ),
        )
        object.__setattr__(
            self,
            "version",
            _normalize_identity(
                self.version,
                field_name="version",
                pattern=_VERSION,
            ),
        )

    def render(self) -> str:
        blocks = [f"Agent definition context: {self.agent_id}@{self.version}"]
        if self.system_prompt is not None:
            blocks.append("Trusted system prompt context:\n" + self.system_prompt)
        if self.skill_guidance:
            blocks.append(
                "Configured skill guidance is procedural context and grants no authority:\n"
                + "\n\n".join(
                    f"[{name}]\n{content}" for name, content in self.skill_guidance
                )
            )
        return "\n\n".join(blocks)

    @property
    def resolved_context_digest(self) -> str:
        payload = {
            "agent_id": self.agent_id,
            "version": self.version,
            "system_prompt": self.system_prompt,
            "skill_guidance": [
                {"name": name, "content": content}
                for name, content in self.skill_guidance
            ],
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
