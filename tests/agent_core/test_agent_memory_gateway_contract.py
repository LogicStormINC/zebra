from uuid import uuid4

import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryStatus
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayHit,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)
from pydantic import ValidationError


def memory_id() -> MemoryId:
    return MemoryId(uuid4())


def test_publication_accepts_only_confirmed_governed_memory() -> None:
    publication = ConfirmedMemoryPublication(
        memory_id=memory_id(),
        namespace=" tenant:opaque ",
        text=" prefers concise output ",
        idempotency_key=" delivery:1 ",
    )

    assert publication.memory_status is MemoryStatus.CONFIRMED
    assert publication.namespace == "tenant:opaque"
    assert publication.text == "prefers concise output"
    assert publication.idempotency_key == "delivery:1"

    with pytest.raises(ValidationError, match="confirmed"):
        ConfirmedMemoryPublication.model_validate(
            {
                "memory_id": memory_id(),
                "memory_status": MemoryStatus.CANDIDATE,
                "namespace": "tenant:opaque",
                "text": "unreviewed",
                "idempotency_key": "delivery:2",
            }
        )


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            ConfirmedMemoryPublication,
            {
                "memory_id": memory_id(),
                "namespace": " ",
                "text": "memory",
                "idempotency_key": "delivery:1",
            },
        ),
        (MemoryGatewaySearchRequest, {"namespace": "scope", "query": " "}),
        (
            MemoryGatewayDeleteRequest,
            {"memory_id": memory_id(), "namespace": "scope", "idempotency_key": " "},
        ),
    ],
)
def test_gateway_requests_reject_blank_authority_fields(
    model: type[ConfirmedMemoryPublication]
    | type[MemoryGatewaySearchRequest]
    | type[MemoryGatewayDeleteRequest],
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        model.model_validate(values)


def test_search_hits_expose_revalidation_identity_without_memory_text() -> None:
    identifier = memory_id()
    result = MemoryGatewaySearchResult(
        status=MemoryGatewayStatus.SUCCEEDED,
        hits=(
            MemoryGatewayHit(
                memory_id=identifier,
                provider_ref="provider:42",
                provider_score=0.8,
            ),
        ),
    )

    assert result.hits[0].memory_id == identifier
    assert "text" not in MemoryGatewayHit.model_fields
    assert "confidence" not in MemoryGatewayHit.model_fields


def test_partial_search_can_return_only_revalidatable_hits() -> None:
    result = MemoryGatewaySearchResult(
        status=MemoryGatewayStatus.PARTIAL,
        hits=(MemoryGatewayHit(memory_id=memory_id(), provider_ref="provider:42"),),
        detail="provider result cap reached",
    )

    assert len(result.hits) == 1


def test_gateway_requests_and_scores_are_bounded() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 100"):
        MemoryGatewaySearchRequest(namespace="scope", query="memory", limit=101)

    with pytest.raises(ValidationError, match="finite number"):
        MemoryGatewayHit(
            memory_id=memory_id(),
            provider_ref="provider:42",
            provider_score=float("nan"),
        )


@pytest.mark.parametrize(
    "status",
    [
        MemoryGatewayStatus.DEGRADED,
        MemoryGatewayStatus.DISABLED,
        MemoryGatewayStatus.NOT_FOUND,
    ],
)
def test_unavailable_search_cannot_leak_unvalidated_hits(
    status: MemoryGatewayStatus,
) -> None:
    with pytest.raises(ValidationError, match="cannot expose hits"):
        MemoryGatewaySearchResult(
            status=status,
            hits=(MemoryGatewayHit(memory_id=memory_id(), provider_ref="provider:42"),),
        )


def test_degraded_and_disabled_results_are_normal_values() -> None:
    assert MemoryGatewaySearchResult(
        status=MemoryGatewayStatus.DEGRADED,
        detail="provider timeout",
    ).hits == ()
    assert MemoryGatewayMutationResult(status=MemoryGatewayStatus.DISABLED).provider_ref is None


def test_mutation_result_requires_provider_ref_only_after_success() -> None:
    result = MemoryGatewayMutationResult(
        status=MemoryGatewayStatus.SUCCEEDED,
        provider_ref=" provider:42 ",
    )
    assert result.provider_ref == "provider:42"

    with pytest.raises(ValidationError, match="requires provider_ref"):
        MemoryGatewayMutationResult(status=MemoryGatewayStatus.SUCCEEDED)

    with pytest.raises(ValidationError, match="cannot expose provider_ref"):
        MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.DEGRADED,
            provider_ref="provider:42",
        )


def test_contract_schema_contains_no_provider_specific_types() -> None:
    schemas = " ".join(
        str(model.model_json_schema())
        for model in (
            ConfirmedMemoryPublication,
            MemoryGatewaySearchRequest,
            MemoryGatewayDeleteRequest,
            MemoryGatewayMutationResult,
            MemoryGatewaySearchResult,
        )
    ).lower()

    assert "mem0" not in schemas
    assert "redis" not in schemas
