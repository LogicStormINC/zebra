"""Exact bounded public assistant text; original model history remains authoritative."""

from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Literal

from agent_core.contracts.model_commentary import (
    COMMENTARY_CHUNK_CHARACTERS,
    MAX_COMMENTARY_CHUNKS,
    ModelCommentaryChunk,
    ModelCommentaryPlan,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft


def text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def eligible(payload: Mapping[str, object]) -> bool:
    text = payload.get("assistant_message")
    attempt = payload.get("attempt_number")
    return (
        payload.get("response_stage") == "tool_loop"
        and isinstance(text, str)
        and bool(text.strip())
        and text.strip() != "Tool calls proposed."
        and isinstance(payload.get("model_call_id"), str)
        and bool(str(payload["model_call_id"]).strip())
        and type(attempt) is int
        and attempt > 0
    )


def plan_response(payload: Mapping[str, object], reserved: int) -> dict[str, object]:
    result = dict(payload)
    if not eligible(payload):
        return result
    text = str(payload["assistant_message"])
    count = (len(text) + COMMENTARY_CHUNK_CHARACTERS - 1) // COMMENTARY_CHUNK_CHARACTERS
    call = text_hash(str(payload["model_call_id"]))[:32]
    disposition: Literal["admitted", "quota_exhausted", "text_limit"] = (
        "text_limit"
        if count > MAX_COMMENTARY_CHUNKS
        else "quota_exhausted"
        if reserved + count > MAX_COMMENTARY_CHUNKS
        else "admitted"
    )
    plan = ModelCommentaryPlan(
        disposition=disposition,
        output_ids=[
            f"public:{payload['attempt_number']}:model-commentary:{call}:{i}" for i in range(count)
        ]
        if disposition == "admitted"
        else [],
        source_sha256=text_hash(text),
    )
    result["public_commentary"] = plan.model_dump()
    return result


def commentary_outputs(payload: Mapping[str, object]) -> tuple[HarnessEventDraft, ...]:
    raw = payload.get("public_commentary")
    if raw is None:
        return ()
    plan = ModelCommentaryPlan.model_validate(raw)
    if not eligible(payload) or plan.source_sha256 != text_hash(str(payload["assistant_message"])):
        raise ValueError("commentary plan disagrees with public assistant source")
    if plan.disposition != "admitted":
        return ()
    text = str(payload["assistant_message"])
    expected = plan_response(payload, 0)["public_commentary"]
    if plan.model_dump() != expected:
        raise ValueError("commentary source chunk plan is not deterministic")
    return tuple(
        HarnessEventDraft(
            EventType.PUBLIC_OUTPUT,
            EventActor.HARNESS,
            {
                "schema_version": 1,
                "attempt_number": payload["attempt_number"],
                "output_id": output_id,
                "kind": "commentary",
                "phase": "model_commentary",
                "origin": "model",
                "content": text[i * plan.chunk_characters : (i + 1) * plan.chunk_characters],
                "status": "complete",
                "meaningful": False,
                "evidence_refs": [],
                "model_call_id": payload["model_call_id"],
                "commentary_chunk": ModelCommentaryChunk(
                    index=i, count=len(plan.output_ids), source_sha256=plan.source_sha256
                ).model_dump(),
            },
        )
        for i, output_id in enumerate(plan.output_ids)
    )


class ModelCommentaryPublisher:
    def __init__(
        self,
        sink: Callable[[HarnessEventDraft], None],
        output_published: Callable[[str], bool],
        reserved: int = 0,
    ) -> None:
        self._sink, self._output_published, self.reserved = sink, output_published, reserved
        self._seen: set[str] = set()

    def publish(self, payload: Mapping[str, object]) -> None:
        drafts = commentary_outputs(payload)
        self.reserved += sum(d.payload["output_id"] not in self._seen for d in drafts)
        for draft in drafts:
            key = str(draft.payload["output_id"])
            if key not in self._seen and not self._output_published(key):
                self._sink(draft)
            self._seen.add(key)
