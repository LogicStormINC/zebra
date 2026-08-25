"""Client state injection into the agent context (ADR-CLIENT-01).

Builds one bounded ``client_state`` ContextItem from a persisted
ClientStateSnapshot. Worker recovery reads only the persisted snapshot;
raw AG-UI command payloads never reach the prompt.
"""

from __future__ import annotations

from agent_core.domain.client_context import (
    ClientStateSnapshot,
    validate_client_state_snapshot,
)
from agent_core.ports.context_compiler import RuntimeEvidenceInput

from agent_context.models import (
    CLIENT_STATE_SOURCE_TYPES,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
    TrustLevel,
)

MAX_CLIENT_STATE_ITEM_CHARS = 8_192


class ClientStateContextError(ValueError):
    pass


def client_state_context_item(snapshot: ClientStateSnapshot) -> ContextItem:
    """Render the snapshot as a truncated, untrusted context item."""

    validate_client_state_snapshot(snapshot)
    rendered = _render(snapshot)
    if len(rendered) > MAX_CLIENT_STATE_ITEM_CHARS:
        rendered = rendered[: MAX_CLIENT_STATE_ITEM_CHARS - 1] + "…"
    return ContextItem(
        kind=ContextItemKind.CLIENT_STATE,
        title=(
            "Mounted client state"
            f" (revision {snapshot.ui_revision})"
        ),
        content=rendered,
        provenance=ContextProvenance(
            source_type="client_state",
            locator=snapshot.client_session_id,
        ),
        trust_level=TrustLevel.USER,
        priority=20,
        token_count=max(1, len(rendered) // 4),
        metadata={
            "frontend_app_id": snapshot.frontend_app_id,
            "profile_digest": snapshot.profile_digest,
            "ui_revision": snapshot.ui_revision,
            "state_digest": snapshot.state_digest,
        },
    )


def _render(snapshot: ClientStateSnapshot) -> str:
    import json

    header = (
        f"client_session={snapshot.client_session_id}"
        f" ui_revision={snapshot.ui_revision}"
    )
    if snapshot.frontend_app_id:
        header += f" frontend_app={snapshot.frontend_app_id}"
    if snapshot.profile_digest:
        header += f" profile_digest={snapshot.profile_digest[:12]}"
    body = json.dumps(
        snapshot.state, sort_keys=True, separators=(",", ":"), default=str
    )
    if snapshot.redacted_keys:
        header += f" redacted={list(snapshot.redacted_keys)}"
    return f"{header}\n{body}"


def client_state_is_allowed_source(source_type: str) -> bool:
    return source_type in CLIENT_STATE_SOURCE_TYPES


def client_state_evidence(snapshot: ClientStateSnapshot) -> RuntimeEvidenceInput:
    """Build the worker-side runtime evidence for a persisted snapshot."""

    validate_client_state_snapshot(snapshot)
    return RuntimeEvidenceInput(
        kind="client_state",
        summary=(
            f"Mounted client state at UI revision {snapshot.ui_revision}"
            f" (digest {snapshot.state_digest[:12]})"
        ),
        details=tuple(f"redacted: {key}" for key in snapshot.redacted_keys),
        metadata={
            "client_session_id": snapshot.client_session_id,
            "frontend_app_id": snapshot.frontend_app_id,
            "profile_digest": snapshot.profile_digest,
            "ui_revision": snapshot.ui_revision,
            "state": snapshot.state,
            "state_digest": snapshot.state_digest,
        },
    )
