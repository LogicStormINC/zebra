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
    sanitized_state: dict[str, object]


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
            raise AgUiClientAdmissionError("handler functions cannot enter the command payload")
    if profile is None:
        if declared or state:
            raise AgUiClientAdmissionError(
                "no published frontend profile accepts these tools or state fields"
            )
    else:
        published = profile.action_names()
        unknown = [name for name in declared if name not in published]
        if unknown:
            raise AgUiClientAdmissionError(
                f"tools not published in the frontend profile: {unknown}"
            )
    sanitized, redacted = redact_client_state(state or {})
    if profile is not None:
        readable_contracts = {item.name: item for item in profile.readables}
        unknown_state = sorted(set(sanitized) - set(readable_contracts))
        if unknown_state:
            raise AgUiClientAdmissionError(
                f"state fields not published as frontend readables: {unknown_state}"
            )
        for name, value in sanitized.items():
            contract = readable_contracts[name]
            value_bytes = len(_canonical_json(value).encode())
            if value_bytes > contract.max_state_bytes:
                raise AgUiClientAdmissionError(f"readable {name} exceeds its state byte budget")
            _validate_value(value, contract.state_schema, path=name)
    encoded = _canonical_json(sanitized).encode()
    if len(encoded) > MAX_COMMAND_STATE_BYTES:
        raise AgUiClientAdmissionError(f"state snapshot exceeds {MAX_COMMAND_STATE_BYTES} bytes")
    return AgUiClientAdmission(
        mounted_tools=tuple(sorted(set(declared))),
        state_digest=sha256(encoded).hexdigest(),
        state_bytes=len(encoded),
        redacted_keys=tuple(sorted(redacted)),
        sanitized_state=sanitized,
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


def _validate_value(value: object, schema: dict[str, object], *, path: str) -> None:
    """Validate the restricted schema subset accepted by capability contracts."""

    if not schema:
        return
    expected = schema.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if isinstance(expected, str) and not type_matches.get(expected, False):
        raise AgUiClientAdmissionError(f"readable {path} does not match type {expected}")
    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        raise AgUiClientAdmissionError(f"readable {path} is outside its enum")
    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise AgUiClientAdmissionError(f"readable {path} is too short")
        if isinstance(maximum, int) and len(value) > maximum:
            raise AgUiClientAdmissionError(f"readable {path} is too long")
    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            raise AgUiClientAdmissionError(f"readable {path} is below its minimum")
        if isinstance(maximum, int | float) and value > maximum:
            raise AgUiClientAdmissionError(f"readable {path} exceeds its maximum")
    if isinstance(value, dict):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        required = schema.get("required")
        required = required if isinstance(required, list) else []
        missing = [name for name in required if name not in value]
        if missing:
            raise AgUiClientAdmissionError(f"readable {path} is missing {missing}")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise AgUiClientAdmissionError(f"readable {path} has undeclared fields: {unknown}")
        for name, nested in value.items():
            child = properties.get(name)
            if isinstance(child, dict):
                _validate_value(nested, child, path=f"{path}.{name}")
    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise AgUiClientAdmissionError(f"readable {path} has too few items")
        if isinstance(maximum, int) and len(value) > maximum:
            raise AgUiClientAdmissionError(f"readable {path} has too many items")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, nested in enumerate(value):
                _validate_value(nested, items, path=f"{path}[{index}]")
