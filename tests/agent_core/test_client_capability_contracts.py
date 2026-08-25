from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import (
    ClientActionContract,
    ClientActionRisk,
    ClientCapabilityError,
    ClientCapabilitySizeError,
    ClientComponentContract,
    ClientReadableContract,
    ClientSelectorForbiddenError,
    DuplicateClientCapabilityError,
    ForbiddenClientCapabilityFieldError,
    FrontendCapabilityProfileVersion,
    MountedCapabilityNarrowingError,
    MountedCapabilitySnapshot,
    UnpublishableClientActionRiskError,
    canonical_client_capability_digest,
    validate_profile_for_publish,
)
from pydantic import ValidationError

PUBLISHED_AT = datetime(2026, 8, 25, tzinfo=UTC)


def _action(name: str = "trench.ui.event.open", **overrides) -> ClientActionContract:
    payload = {
        "name": name,
        "risk": ClientActionRisk.PRESENTATION,
        "parameters": {
            "type": "object",
            "properties": {"eventId": {"type": "string"}},
            "required": ["eventId"],
            "additionalProperties": False,
        },
    }
    payload.update(overrides)
    return ClientActionContract.model_validate(payload)


def _profile(**overrides) -> FrontendCapabilityProfileVersion:
    payload = {
        "frontend_app_id": "trench-web",
        "revision": 1,
        "actions": (_action(),),
        "readables": (
            ClientReadableContract(
                name="trench.ui.route",
                state_schema={
                    "type": "object",
                    "properties": {"route": {"type": "string"}},
                },
            ),
        ),
        "published_at": PUBLISHED_AT,
    }
    payload.update(overrides)
    return FrontendCapabilityProfileVersion.model_validate(payload)


def test_same_profile_content_yields_same_digest() -> None:
    assert _profile().profile_digest == _profile().profile_digest


def test_different_revision_changes_digest() -> None:
    assert _profile().profile_digest != _profile(revision=2).profile_digest


def test_duplicate_capability_names_are_rejected() -> None:
    with pytest.raises(ValidationError) as info:
        _profile(
            readables=(ClientReadableContract(name="trench.ui.event.open"),)
        )
    assert isinstance(_unwrap_domain(info), DuplicateClientCapabilityError)


def test_parameters_must_use_restricted_json_schema() -> None:
    with pytest.raises(ValueError):
        _action(parameters={"type": "object", "patternProperties": {"x": {}}})


def test_selector_strings_are_forbidden() -> None:
    with pytest.raises(ValidationError) as info:
        _action(parameters={
            "type": "object",
            "properties": {"node": {"type": "string", "description": "#main"}},
        })
    assert isinstance(_unwrap_domain(info), ClientSelectorForbiddenError)


def test_secret_field_names_are_forbidden() -> None:
    with pytest.raises(ValidationError) as info:
        _action(parameters={
            "type": "object",
            "properties": {"apiToken": {"type": "string"}},
        })
    assert isinstance(_unwrap_domain(info), ForbiddenClientCapabilityFieldError)


def test_business_write_risk_cannot_be_published() -> None:
    profile = _profile(
        actions=(
            _action(
                name="trench.report.publish",
                risk=ClientActionRisk.BUSINESS_WRITE_FORBIDDEN,
            ),
        )
    )
    with pytest.raises(UnpublishableClientActionRiskError):
        validate_profile_for_publish(profile)


def test_publish_gate_accepts_a_valid_profile() -> None:
    validate_profile_for_publish(_profile())


def test_profile_contract_count_is_bounded() -> None:
    actions = tuple(_action(name=f"trench.ui.action.{index}") for index in range(200))
    with pytest.raises(ValidationError) as info:
        _profile(actions=actions)
    assert isinstance(_unwrap_domain(info), ClientCapabilitySizeError)


def test_mounted_snapshot_must_narrow_a_matching_profile() -> None:
    profile = _profile()
    snapshot = MountedCapabilitySnapshot(
        client_session_id=uuid4(),
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_readables=("trench.ui.route",),
        mounted_actions=("trench.ui.event.open",),
        ui_revision=3,
        mounted_at=PUBLISHED_AT,
    )
    snapshot.ensure_subset_of(profile)
    stale = snapshot.model_copy(
        update={"profile_digest": "0" * 64}
    )
    with pytest.raises(MountedCapabilityNarrowingError):
        stale.ensure_subset_of(profile)
    grown = snapshot.model_copy(update={"mounted_actions": ("trench.ui.absent",)})
    with pytest.raises(MountedCapabilityNarrowingError):
        grown.ensure_subset_of(profile)


def test_component_contract_is_publishable_metadata_only() -> None:
    component = ClientComponentContract(name="trench.ui.panel.card")
    assert component.name == "trench.ui.panel.card"


def test_canonical_digest_is_stable_across_key_order() -> None:
    left = canonical_client_capability_digest({"b": 1, "a": 2})
    right = canonical_client_capability_digest({"a": 2, "b": 1})
    assert left == right

def _unwrap_domain(exc_info) -> Exception | None:
    for error in exc_info.value.errors():
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, ClientCapabilityError):
            return cause
    return None
