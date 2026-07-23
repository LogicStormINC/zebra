from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextCapsuleValidationError,
    ContextSourceEventRange,
)
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import EventStorePort
from agent_storage import (
    SQLiteContextLifecycleStore,
    SQLiteProviderContinuationStore,
)

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


def persist_context_compaction(
    draft: HarnessEventDraft,
    *,
    recorder: DurableHarnessEventRecorder,
    event_store: EventStorePort,
    lifecycle_store: SQLiteContextLifecycleStore,
) -> None:
    """Persist a compaction capsule, degrading gracefully on validation failure.

    CTX-ART-01: compaction is an optimization, not the source of truth. If the
    candidate capsule fails durable validation, we record a non-terminal
    ``CONTEXT_COMPACTION_REJECTED`` diagnostic, preserve the existing active
    projection, and let the Agent continue with the in-memory compacted
    messages. This implements design doc §L4 item 4: "验证失败时回退到确定性
    Capsule;不得替换当前可用投影". A capsule validation failure must NEVER
    become ``session_failed``.
    """
    raw_capsule = draft.payload.get("capsule")
    if not isinstance(raw_capsule, dict):
        recorder.append_draft(draft)
        return
    events = event_store.list_for_session(recorder.session.session_id)
    capsule = _durable_capsule(ContextCapsule.model_validate(raw_capsule), events)
    active = lifecycle_store.get_active_capsule(recorder.session.session_id)
    readable_refs = frozenset(
        ref
        for ref in (*capsule.artifact_refs, *capsule.recent_exact_tail_refs)
        if not ref.startswith("file://") or _is_readable(ref)
    )
    compaction_event = SessionEvent.create(
        session_id=recorder.session.session_id,
        sequence=recorder.next_sequence,
        event_type=draft.event_type,
        actor=draft.actor,
        payload=draft.payload,
    )
    if capsule.source_event_range is None:
        raise ValueError("durable capsule source event range is required")
    try:
        stored = lifecycle_store.persist_capsule_and_advance(
            session_id=recorder.session.session_id,
            capsule=capsule,
            validation_context=ContextCapsuleValidationContext(
                expected_source_hash=capsule.source_hash,
                expected_source_event_range=capsule.source_event_range,
                unresolved_tool_call_ids=frozenset(
                    tool.call_id for tool in capsule.pending_tools
                ),
                protected_user_constraints=frozenset(capsule.protected_user_constraints),
                approval_and_policy_state=frozenset(capsule.approvals_and_policy_state),
                readable_artifact_refs=readable_refs,
            ),
            sequence=recorder.next_sequence,
            expected_active_capsule_id=active.capsule.capsule_id if active else None,
            compaction_event=compaction_event,
        )
    except ContextCapsuleValidationError as exc:
        # Compaction is optimization, not source of truth. Preserve the existing
        # active projection and record a non-terminal diagnostic so the Agent
        # continues with the in-memory compacted conversation.
        _record_compaction_rejected(
            recorder=recorder,
            capsule=capsule,
            rejection_reason=str(exc),
            fallback_mode="retain_active_projection",
        )
        return
    recorder.accept_persisted_event(compaction_event)
    recorder.accept_persisted_event(stored.event)


def _record_compaction_rejected(
    *,
    recorder: DurableHarnessEventRecorder,
    capsule: ContextCapsule,
    rejection_reason: str,
    fallback_mode: str,
) -> None:
    """Record a non-terminal diagnostic when capsule validation fails."""
    recorder.append(
        EventType.CONTEXT_COMPACTION_REJECTED,
        EventActor.SYSTEM,
        {
            "capsule_id": capsule.capsule_id,
            "rejection_reason": rejection_reason,
            "fallback_mode": fallback_mode,
            "preserved_active_projection": True,
        },
    )


def recover_provider_continuation(
    events: list[SessionEvent],
    store: SQLiteProviderContinuationStore,
) -> ProviderContinuationRef | None:
    for event in reversed(events):
        if event.event_type is not EventType.CONTEXT_CONTINUATION_SELECTED:
            continue
        payload = event.payload
        if payload.get("mode") != "provider_native":
            return None
        artifact_id = _payload_text(payload, "artifact_id")
        provider = _payload_text(payload, "provider")
        model_name = _payload_text(payload, "model_name")
        capability_version = _payload_text(payload, "capability_version")
        if None in (artifact_id, provider, model_name, capability_version):
            return None
        loaded = store.load_compatible(
            artifact_id or "",
            tenant_id="local",
            provider=provider or "",
            model_name=model_name or "",
            capability_version=capability_version or "",
        )
        return loaded.artifact.reference if loaded is not None else None
    return None


def _durable_capsule(
    capsule: ContextCapsule,
    events: list[SessionEvent],
) -> ContextCapsule:
    event_range = ContextSourceEventRange(
        start_sequence=events[0].sequence,
        end_sequence=events[-1].sequence,
    )
    approvals = tuple(
        _approval_state(event)
        for event in events
        if event.event_type
        in {
            EventType.POLICY_DECISION_MADE,
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
        }
    )
    return capsule.model_copy(
        update={
            "source_event_range": event_range,
            "protected_user_constraints": capsule.constraints,
            "approvals_and_policy_state": approvals,
        }
    )


def _is_readable(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return False
    return Path(unquote(parsed.path)).is_file()


def _approval_state(event: SessionEvent) -> str:
    detail = event.payload.get("decision", event.payload.get("reason", "recorded"))
    return f"{event.event_type.value}:{detail}"


def _payload_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
