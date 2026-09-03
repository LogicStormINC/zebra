"""Worker seam that binds staged provider bytes to one canonical Event."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import Lock

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_artifact_id
from agent_core.harness.models import HarnessEventDraft
from agent_core.ports import CloudProviderContinuationStorePort

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder


@dataclass(frozen=True, slots=True)
class _PendingContinuation:
    continuation_id: str
    reference: ProviderContinuationRef
    payload: bytes
    maximum_ttl_seconds: int | None


class CloudProviderContinuationCoordinator:
    """Keep export local until the cloud aggregate commits payload and Event."""

    def __init__(
        self,
        *,
        store: CloudProviderContinuationStorePort,
        scope: OpaqueAuthorityScope,
        session_id: SessionId,
    ) -> None:
        self._store = store
        self._scope = scope
        self._session_id = session_id
        self._pending: dict[str, _PendingContinuation] = {}
        self._lock = Lock()

    def prepare(
        self,
        reference: ProviderContinuationRef,
        payload: bytes | None,
        maximum_ttl_seconds: int | None,
    ) -> str | None:
        if payload is None:
            return None
        continuation_id = str(new_artifact_id())
        pending = _PendingContinuation(
            continuation_id=continuation_id,
            reference=reference,
            payload=payload,
            maximum_ttl_seconds=maximum_ttl_seconds,
        )
        with self._lock:
            self._pending[continuation_id] = pending
        return continuation_id

    def append_draft(
        self,
        draft: HarnessEventDraft,
        recorder: DurableHarnessEventRecorder,
    ) -> SessionEvent:
        if (
            draft.event_type is not EventType.CONTEXT_CONTINUATION_SELECTED
            or draft.payload.get("mode") != "provider_native"
        ):
            return recorder.append_draft(draft)
        artifact_id = draft.payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ValueError("cloud continuation Event is missing continuation_id")
        with self._lock:
            pending = self._pending.get(artifact_id)
        if pending is None:
            raise ValueError("cloud continuation Event has no staged payload")
        authority = recorder.worker_mutation_authority
        if authority is None:
            raise ValueError("cloud continuation requires Worker mutation authority")
        event = recorder.prepare(draft.event_type, draft.actor, self._event_payload(draft, pending))
        event = event.model_copy(update={"idempotency_key": f"provider-continuation:{artifact_id}"})
        committed = self._store.commit_worker_selection(
            scope=self._scope,
            authority=authority,
            continuation_id=artifact_id,
            session=recorder.session,
            workspace=recorder.workspace,
            reference=pending.reference,
            opaque_payload=pending.payload,
            maximum_ttl_seconds=pending.maximum_ttl_seconds,
            selection_event=event,
        )
        recorder.accept_committed_aggregate(
            committed.event,
            session=committed.session,
            workspace=committed.workspace,
        )
        with self._lock:
            self._pending.pop(artifact_id, None)
        return committed.event

    def recover(self, events: list[SessionEvent]) -> ProviderContinuationRef | None:
        """Resolve the last cloud selection without touching the local store."""
        for event in reversed(events):
            if event.event_type is not EventType.CONTEXT_CONTINUATION_SELECTED:
                continue
            payload = event.payload
            if payload.get("mode") != "provider_native":
                return None
            if (
                payload.get("authority_issuer") != self._scope.authority_issuer
                or payload.get("namespace_id") != self._scope.namespace_id
                or event.session_id != self._session_id
            ):
                return None
            artifact_id = _payload_text(payload, "artifact_id")
            provider = _payload_text(payload, "provider")
            model_name = _payload_text(payload, "model_name")
            capability_version = _payload_text(payload, "capability_version")
            if None in (artifact_id, provider, model_name, capability_version):
                return None
            loaded = self._store.load_compatible(
                artifact_id or "",
                scope=self._scope,
                session_id=self._session_id,
                provider=provider or "",
                model_name=model_name or "",
                capability_version=capability_version or "",
            )
            return loaded.artifact.reference if loaded is not None else None
        return None

    def _event_payload(
        self,
        draft: HarnessEventDraft,
        pending: _PendingContinuation,
    ) -> dict[str, object]:
        payload = dict(draft.payload)
        payload.update(
            {
                "artifact_id": pending.continuation_id,
                "authority_issuer": self._scope.authority_issuer,
                "namespace_id": self._scope.namespace_id,
                "payload_sha256": sha256(pending.payload).hexdigest(),
            }
        )
        return payload


def _payload_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
