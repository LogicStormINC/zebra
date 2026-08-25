"""AG-UI command client admission (ADR-CLIENT-01).

Converts the AG-UI ``RunAgentInput`` ``tools``/``state`` payload into
mounted-capability declarations and a bounded state snapshot. Published
frontend profiles stay the configuration source of truth: undeclared
tools and digest drift fail closed, and handler functions can never
enter the payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from agent_core.domain.client_capabilities import (
    FrontendCapabilityProfileVersion,
    MountedCapabilitySnapshot,
)
from agent_core.domain.identifiers import ClientSessionId

MAX_COMMAND_STATE_BYTES = 65_536
REDACTED_KEYS = ("authorization", "cookie", "secret", "token", "password")
REDACTED = "__redacted__"


class AgUiClientAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class AgUiClientAdmission:
    """References stored on the command; raw payloads never persist."""

    mounted_tools: tuple[str, ...]
    state_digest: str
    state_bytes: int
    redacted_keys: tuple[str, ...]


def admit_agui_client_payload(
    *,
    tools: list[dict[str, object]] | tuple[dict[str, object], ...] | None,
    state: dict[str, object] | None,
    profile: FrontendCapabilityProfileVersion | None,
) -> AgUiClientAdmission:
    """Validate the AG-UI tool declarations and state snapshot."""

    declared: list[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            raise AgUiClientAdmissionError("tool declarations must be objects")
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AgUiClientAdmissionError("tool declarations require a name")
        declared.append(name.strip())
        if any(key in tool for key in ("handler", "execute", "code", "script")):
            raise AgUiClientAdmissionError(
                "handler functions cannot enter the command payload"
            )
    if profile is None:
        if declared:
            raise AgUiClientAdmissionError(
                "no published frontend profile accepts these tools"
            )
    else:
        published = profile.action_names()
        unknown = [name for name in declared if name not in published]
        if unknown:
            raise AgUiClientAdmissionError(
                f"tools not published in the frontend profile: {unknown}"
            )
    sanitized, redacted = redact_client_state(state or {})
    encoded = _canonical_json(sanitized).encode()
    if len(encoded) > MAX_COMMAND_STATE_BYTES:
        raise AgUiClientAdmissionError(
            f"state snapshot exceeds {MAX_COMMAND_STATE_BYTES} bytes"
        )
    return AgUiClientAdmission(
        mounted_tools=tuple(sorted(set(declared))),
        state_digest=sha256(encoded).hexdigest(),
        state_bytes=len(encoded),
        redacted_keys=tuple(sorted(redacted)),
    )


def redact_client_state(
    state: dict[str, object],
) -> tuple[dict[str, object], list[str]]:
    """Deep-copy the state with sensitive keys replaced."""

    redacted: list[str] = []

    def _walk(value: object, path: str) -> object:
        if isinstance(value, dict):
            walked: dict[str, object] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in REDACTED_KEYS):
                    redacted.append(path + str(key))
                    walked[str(key)] = REDACTED
                else:
                    walked[str(key)] = _walk(item, path + str(key) + ".")
            return walked
        if isinstance(value, list):
            return [_walk(item, path) for item in value]
        return value

    return _walk(state, ""), redacted  # type: ignore[return-value]


def mounted_snapshot_from_admission(
    admission: AgUiClientAdmission,
    *,
    client_session_id: ClientSessionId,
    profile: FrontendCapabilityProfileVersion,
    ui_revision: int,
) -> MountedCapabilitySnapshot:
    """Materialize the mounted snapshot declared by this command."""

    snapshot = MountedCapabilitySnapshot(
        client_session_id=client_session_id,
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_readables=tuple(
            sorted(profile.readable_names()),
        ),
        mounted_actions=admission.mounted_tools,
        ui_revision=ui_revision,
        mounted_at=datetime.now(UTC),
    )
    snapshot.ensure_subset_of(profile)
    return snapshot


def _canonical_json(payload: object) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
