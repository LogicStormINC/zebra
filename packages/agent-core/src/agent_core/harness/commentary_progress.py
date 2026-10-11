"""Validate source reservations and exact chunk publication during bounded progress fold."""

from collections.abc import Mapping
from typing import Any

from agent_core.contracts.model_commentary import MAX_COMMENTARY_CHUNKS, ModelCommentaryPlan
from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.harness.model_commentary import commentary_outputs, text_hash
from agent_core.ports.model_commentary_progress import PendingModelCommentary
from agent_core.ports.task_projection_checkpoints import CheckpointConflict


def reserve_commentary(
    payload: Mapping[str, object], sequence: int, values: dict[str, Any]
) -> None:
    if payload.get("public_commentary") is None:
        return  # Historical model responses do not mint new publication authority.
    plan = ModelCommentaryPlan.model_validate(payload["public_commentary"])
    drafts = commentary_outputs(payload)
    if not drafts:
        return
    if values["pending_commentary"] is not None:
        raise CheckpointConflict("new model commentary precedes completion of its durable source")
    reserved = values["commentary_reserved_count"] + len(drafts)
    if reserved > MAX_COMMENTARY_CHUNKS:
        raise CheckpointConflict("model commentary exceeds its separate Run quota")
    values["commentary_reserved_count"] = reserved
    attempt = payload["attempt_number"]
    assert type(attempt) is int
    values["pending_commentary"] = PendingModelCommentary(
        source_sequence=sequence,
        attempt_number=attempt,
        model_call_id=str(payload["model_call_id"]),
        output_ids=plan.output_ids,
        source_sha256=plan.source_sha256,
        chunk_hashes=[text_hash(str(d.payload["content"])) for d in drafts],
    ).model_dump()


def accept_commentary(output: PublicOutputPayload, values: dict[str, Any]) -> None:
    pending = values["pending_commentary"]
    chunk = output.commentary_chunk
    if pending is None or chunk is None:
        raise CheckpointConflict("model commentary has no durable pending source")
    p = PendingModelCommentary.model_validate(pending)
    if (
        output.attempt_number != p.attempt_number
        or output.model_call_id != p.model_call_id
        or chunk.index != p.next_index
        or chunk.count != len(p.output_ids)
        or chunk.source_sha256 != p.source_sha256
        or output.output_id != p.output_ids[p.next_index]
        or text_hash(output.content) != p.chunk_hashes[p.next_index]
    ):
        raise CheckpointConflict("model commentary differs from its exact source chunk")
    values["commentary_published_count"] += 1
    values["pending_commentary"] = (
        None
        if p.next_index + 1 == len(p.output_ids)
        else {**p.model_dump(), "next_index": p.next_index + 1}
    )
