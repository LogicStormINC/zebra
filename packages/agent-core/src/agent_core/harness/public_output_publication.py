"""Construct bounded narration drafts independently of scheduling and receipt reduction."""

from hashlib import sha256
from typing import TYPE_CHECKING

from agent_core.contracts.public_output import EvidenceBasis, PublicOutputPolicy, PublicReadFacts
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output_lifecycle import current_public_output_deadline

if TYPE_CHECKING:
    from agent_core.harness.public_output import ProgressiveEventSink


def narration_draft(
    output_id: str,
    kind: str,
    phase: str,
    content: str,
    *,
    attempt: int,
    policy: PublicOutputPolicy,
    meaningful: bool,
    evidence_basis: EvidenceBasis | None,
    evidence_refs: list[str] | None,
    replaces_output_id: str | None,
    origin: str,
    model_call_id: str | None,
) -> HarnessEventDraft:
    payload: dict[str, object] = {
        "schema_version": 1,
        "attempt_number": attempt,
        "output_id": output_id,
        "kind": kind,
        "phase": phase,
        "origin": origin,
        "content": content[: policy.max_characters],
        "status": "complete",
        "meaningful": meaningful,
        "policy_version": policy.version,
        "evidence_refs": evidence_refs or [],
    }
    if replaces_output_id is not None:
        payload["replaces_output_id"] = replaces_output_id
    if evidence_basis is not None:
        payload["evidence_basis"] = evidence_basis
    if model_call_id is not None:
        payload["model_call_id"] = model_call_id
    return HarnessEventDraft(EventType.PUBLIC_OUTPUT, EventActor.HARNESS, payload)


def publish_evidence(progress: "ProgressiveEventSink") -> None:
    if not progress._pending:
        return
    basis = next(
        (
            item.evidence_basis
            for item in progress._pending.values()
            if isinstance(item, PublicReadFacts)
        ),
        None,
    )
    refs = [
        ref
        for ref, item in progress._pending.items()
        if not isinstance(item, PublicReadFacts) or item.evidence_basis == basis
    ]
    summaries = list(
        dict.fromkeys(item.summary for ref in refs if (item := progress._pending[ref]) is not None)
    )
    business_summaries = {
        item.summary for ref in refs if isinstance(item := progress._pending[ref], PublicReadFacts)
    }
    content = (
        "\n\n".join(summaries)
        if summaries
        else progress._text(
            f"已收到 {len(refs)} 项成功工具回执，正在整理并核对；这不代表已覆盖全部数据。",
            f"Received {len(refs)} successful tool receipts. "
            "I am consolidating and checking them; this does not imply complete coverage.",
        )
    )
    fingerprint = sha256("\n".join(refs).encode()).hexdigest()[:24]
    if f"public:{progress._attempt}:evidence:{fingerprint}" in progress._seen:
        for ref in refs:
            progress._pending.pop(ref, None)
        return
    if len(content) > progress.policy.max_characters:
        suffix = progress._text(
            "另有回执未在此处展开；这不是完整数据覆盖。",
            "More receipts are omitted here; this is not complete data coverage.",
        )
        bounded: list[str] = []
        for summary in summaries:
            if len("\n\n".join([*bounded, summary, suffix])) <= progress.policy.max_characters:
                bounded.append(summary)
        summaries = [*bounded, suffix] if bounded else []
        content = "\n\n".join([*bounded, suffix])
    meaningful = bool(business_summaries.intersection(summaries))
    persisted = progress.publish(
        f"evidence:{fingerprint}",
        "result" if meaningful and basis == "verified_result" else "commentary",
        "evidence",
        content,
        meaningful=meaningful,
        evidence_basis=basis if meaningful else None,
        evidence_refs=refs,
    )
    for ref in refs:
        progress._pending.pop(ref, None)
    if persisted:
        progress._covered_receipts.update(refs)
        progress._evidence_published = progress._evidence_published or meaningful
        progress._result_published |= meaningful and basis == "verified_result"
    if (
        persisted
        and meaningful
        and len(summaries) > 1
        and progress._expression is not None
        and not progress._closed
        and not progress._closing.is_set()
        and progress._published_count < progress.policy.max_outputs
    ):
        expressed = progress._expression.express(
            summaries, chinese=progress._chinese, deadline=current_public_output_deadline()
        )
        if (
            expressed is not None
            and expressed[0] != content
            and len(expressed[0]) <= progress.policy.max_characters
        ):
            progress.publish(
                f"expression:{fingerprint}",
                "result" if basis == "verified_result" else "commentary",
                "evidence",
                expressed[0],
                meaningful=True,
                evidence_basis=basis,
                evidence_refs=refs,
                origin="model",
                model_call_id=expressed[1],
                replaces_output_id=f"public:{progress._attempt}:evidence:{fingerprint}",
            )
