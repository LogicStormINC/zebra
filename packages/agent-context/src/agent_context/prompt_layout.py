import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

from agent_context.models import CompiledContext, ContextItem, ContextItemKind


class PromptSectionKind(StrEnum):
    STABLE = "stable"
    SEMI_STABLE = "semi_stable"
    DYNAMIC = "dynamic"


@dataclass(frozen=True)
class PromptSection:
    kind: PromptSectionKind
    items: tuple[ContextItem, ...]

    @property
    def rendered_text(self) -> str:
        heading = {
            PromptSectionKind.STABLE: "Stable Context",
            PromptSectionKind.SEMI_STABLE: "Semi-Stable Context",
            PromptSectionKind.DYNAMIC: "Dynamic Context",
        }[self.kind]
        if not self.items:
            return heading + ":\n(none)"
        blocks = [heading + ":"]
        for item in self.items:
            blocks.append(f"[{item.kind.value}] {item.title}\n{item.content}")
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class PromptLayout:
    stable: PromptSection
    semi_stable: PromptSection
    dynamic: PromptSection

    @property
    def rendered_text(self) -> str:
        return "\n\n".join(
            (
                self.stable.rendered_text,
                self.semi_stable.rendered_text,
                self.dynamic.rendered_text,
            )
        )


@dataclass(frozen=True)
class PromptCacheKeyRequest:
    compiled_context: CompiledContext
    task_input: str
    workspace_root: str
    model_profile: str
    policy_summary: str
    tool_manifest: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "task_input",
            "workspace_root",
            "model_profile",
            "policy_summary",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")


def build_prompt_layout(compiled_context: CompiledContext) -> PromptLayout:
    stable_items: list[ContextItem] = []
    semi_stable_items: list[ContextItem] = []
    dynamic_items: list[ContextItem] = []
    for item in compiled_context.items:
        section = _classify_item(item)
        if section is PromptSectionKind.STABLE:
            stable_items.append(item)
        elif section is PromptSectionKind.SEMI_STABLE:
            semi_stable_items.append(item)
        else:
            dynamic_items.append(item)
    return PromptLayout(
        stable=PromptSection(PromptSectionKind.STABLE, tuple(stable_items)),
        semi_stable=PromptSection(PromptSectionKind.SEMI_STABLE, tuple(semi_stable_items)),
        dynamic=PromptSection(PromptSectionKind.DYNAMIC, tuple(dynamic_items)),
    )


def build_prompt_cache_key(request: PromptCacheKeyRequest) -> str:
    layout = build_prompt_layout(request.compiled_context)
    payload = {
        "task_input": request.task_input,
        "workspace_root": request.workspace_root,
        "model_profile": request.model_profile,
        "policy_summary": request.policy_summary,
        "tool_manifest": list(request.tool_manifest),
        "stable_items": [_serialize_item(item) for item in layout.stable.items],
        "semi_stable_items": [_serialize_item(item) for item in layout.semi_stable.items],
        "dynamic_items": [_serialize_item(item) for item in layout.dynamic.items],
    }
    normalized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _classify_item(item: ContextItem) -> PromptSectionKind:
    if item.kind in {
        ContextItemKind.CONVERSATION_SUMMARY,
        ContextItemKind.TOOL_OUTPUT_SUMMARY,
    }:
        return PromptSectionKind.DYNAMIC
    if item.kind is ContextItemKind.REPO_MAP:
        return PromptSectionKind.SEMI_STABLE
    locator = item.provenance.locator.lower()
    if locator.endswith("agents.md") or locator.endswith("readme.md"):
        return PromptSectionKind.STABLE
    return PromptSectionKind.SEMI_STABLE


def _serialize_item(item: ContextItem) -> dict[str, object]:
    return {
        "kind": item.kind.value,
        "title": item.title,
        "content": item.content,
        "source_type": item.provenance.source_type,
        "locator": item.provenance.locator,
        "priority": item.priority,
        "token_count": item.token_count,
    }
