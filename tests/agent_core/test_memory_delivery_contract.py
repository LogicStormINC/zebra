from uuid import uuid4

import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import (
    MemoryDeliveryCertainty,
    MemoryDeliveryOperation,
    MemoryDeliveryOperationRecord,
    MemoryDeliveryScope,
    MemoryDeliveryScopeState,
    MemoryDeliveryState,
    MemoryDeliveryTransition,
)
from agent_core.ports.agent_memory_gateway import (
    MemoryGatewayMutationResult,
    MemoryGatewayStatus,
)
from pydantic import ValidationError

SCOPE_DIGEST = "a" * 64
CONTENT_DIGEST = "b" * 64


def operation(**overrides: object) -> MemoryDeliveryOperationRecord:
    values: dict[str, object] = {
        "memory_id": MemoryId(uuid4()),
        "operation": MemoryDeliveryOperation.PUBLISH,
        "scope_digest": SCOPE_DIGEST,
        "generation": 1,
        "memory_revision": 3,
        "content_digest": CONTENT_DIGEST,
        "idempotency_key": "memory:1:publish:3",
    }
    values.update(overrides)
    return MemoryDeliveryOperationRecord(**values)


def test_scope_requires_opaque_sha256_identity_and_positive_generation() -> None:
    scope = MemoryDeliveryScope(
        deployment_namespace=" tenant-a ",
        scope_digest="A" * 64,
        generation=2,
        revision=4,
    )

    assert scope.deployment_namespace == "tenant-a"
    assert scope.scope_digest == SCOPE_DIGEST
    assert scope.state is MemoryDeliveryScopeState.ACTIVE

    with pytest.raises(ValidationError, match="SHA-256"):
        MemoryDeliveryScope(
            deployment_namespace="tenant-a",
            scope_digest="g" * 64,
            generation=1,
            revision=0,
        )


def test_operation_is_metadata_only_and_normalizes_idempotency_key() -> None:
    record = operation(idempotency_key=" memory:1:publish:3 ")

    assert record.idempotency_key == "memory:1:publish:3"
    assert "text" not in MemoryDeliveryOperationRecord.model_fields
    assert "provider_body" not in MemoryDeliveryOperationRecord.model_fields


@pytest.mark.parametrize(
    ("target", "certainty"),
    [
        (MemoryDeliveryState.PENDING, MemoryDeliveryCertainty.DEFINITE_NO_EFFECT),
        (MemoryDeliveryState.COMPLETED, MemoryDeliveryCertainty.APPLIED),
        (MemoryDeliveryState.COMPLETED, MemoryDeliveryCertainty.DEFINITE_NO_EFFECT),
        (MemoryDeliveryState.UNCERTAIN, MemoryDeliveryCertainty.UNKNOWN),
    ],
)
def test_allowed_transitions_preserve_typed_certainty(
    target: MemoryDeliveryState,
    certainty: MemoryDeliveryCertainty | None,
) -> None:
    current = operation(state=MemoryDeliveryState.IN_FLIGHT)
    transitioned = current.transition(target, certainty=certainty, attempt=2)

    assert transitioned.state is target
    assert transitioned.certainty is certainty
    assert transitioned.attempt == 2


def test_claim_path_is_separate_from_network_outcome() -> None:
    claimed = operation().transition(MemoryDeliveryState.CLAIMED, attempt=1)
    in_flight = claimed.transition(MemoryDeliveryState.IN_FLIGHT)

    assert claimed.certainty is None
    assert in_flight.state is MemoryDeliveryState.IN_FLIGHT


@pytest.mark.parametrize(
    ("current", "target", "certainty"),
    [
        (
            MemoryDeliveryState.PENDING,
            MemoryDeliveryState.UNCERTAIN,
            MemoryDeliveryCertainty.UNKNOWN,
        ),
        (
            MemoryDeliveryState.CLAIMED,
            MemoryDeliveryState.COMPLETED,
            MemoryDeliveryCertainty.APPLIED,
        ),
        (MemoryDeliveryState.UNCERTAIN, MemoryDeliveryState.PENDING, None),
        (MemoryDeliveryState.IN_FLIGHT, MemoryDeliveryState.UNCERTAIN, None),
        (MemoryDeliveryState.COMPLETED, MemoryDeliveryState.PENDING, None),
    ],
)
def test_invalid_transitions_fail_closed(
    current: MemoryDeliveryState,
    target: MemoryDeliveryState,
    certainty: MemoryDeliveryCertainty | None,
) -> None:
    current_certainty = {
        MemoryDeliveryState.COMPLETED: MemoryDeliveryCertainty.APPLIED,
        MemoryDeliveryState.UNCERTAIN: MemoryDeliveryCertainty.UNKNOWN,
    }.get(current)
    with pytest.raises(ValueError, match="transition|requires unknown|completed requires"):
        operation(state=current, certainty=current_certainty).transition(
            target,
            certainty=certainty,
        )


def test_transition_port_request_reuses_same_state_machine() -> None:
    request = MemoryDeliveryTransition(
        idempotency_key="memory:1:publish:3",
        expected_state=MemoryDeliveryState.IN_FLIGHT,
        next_state=MemoryDeliveryState.UNCERTAIN,
        certainty=MemoryDeliveryCertainty.UNKNOWN,
        claim_token="claim-1",
    )

    assert request.next_state is MemoryDeliveryState.UNCERTAIN


@pytest.mark.parametrize(
    ("status", "certainty"),
    [
        (MemoryGatewayStatus.SUCCEEDED, MemoryDeliveryCertainty.UNKNOWN),
        (MemoryGatewayStatus.DEGRADED, MemoryDeliveryCertainty.APPLIED),
        (MemoryGatewayStatus.NOT_FOUND, MemoryDeliveryCertainty.APPLIED),
        (MemoryGatewayStatus.NOT_FOUND, MemoryDeliveryCertainty.UNKNOWN),
    ],
)
def test_gateway_mutation_rejects_status_certainty_contradictions(
    status: MemoryGatewayStatus,
    certainty: MemoryDeliveryCertainty,
) -> None:
    with pytest.raises(ValidationError, match="certainty|applied"):
        MemoryGatewayMutationResult(status=status, certainty=certainty)


def test_gateway_mutation_defaults_are_typed_for_legacy_adapters() -> None:
    assert (
        MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref="provider:1",
        ).certainty
        is MemoryDeliveryCertainty.APPLIED
    )
    assert (
        MemoryGatewayMutationResult(status=MemoryGatewayStatus.DEGRADED).certainty
        is MemoryDeliveryCertainty.UNKNOWN
    )
    assert (
        MemoryGatewayMutationResult(status=MemoryGatewayStatus.NOT_FOUND).certainty
        is MemoryDeliveryCertainty.DEFINITE_NO_EFFECT
    )
