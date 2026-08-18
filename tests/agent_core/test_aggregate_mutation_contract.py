from uuid import uuid4

import pytest
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.ports import AdministrativeMutationCAS, WorkerMutationAuthority
from pydantic import ValidationError


def _fence(*, owner: str = "worker-a", token: int = 3) -> LeaseFence:
    return LeaseFence(
        control_plane_epoch=uuid4(),
        fencing_token=token,
        owner_instance_id=owner,
    )


def _worker_authority() -> WorkerMutationAuthority:
    return WorkerMutationAuthority(
        deployment_namespace="cloud-a",
        session_id=SessionId(uuid4()),
        lease_fence=_fence(),
        expected_stream_revision=7,
    )


def test_worker_mutation_authority_carries_complete_fence_and_revision() -> None:
    authority = _worker_authority()

    assert authority.deployment_namespace == "cloud-a"
    assert authority.expected_stream_revision == 7
    assert authority.lease_fence.fencing_token == 3


@pytest.mark.parametrize(
    "field",
    [
        "deployment_namespace",
        "session_id",
        "lease_fence",
        "expected_stream_revision",
    ],
)
def test_worker_mutation_authority_requires_every_field(field: str) -> None:
    values = _worker_authority().model_dump()
    del values[field]

    with pytest.raises(ValidationError):
        WorkerMutationAuthority.model_validate(values)


@pytest.mark.parametrize(
    "field",
    ["control_plane_epoch", "fencing_token", "owner_instance_id"],
)
def test_worker_mutation_authority_requires_complete_fence(field: str) -> None:
    values = _worker_authority().model_dump()
    del values["lease_fence"][field]

    with pytest.raises(ValidationError):
        WorkerMutationAuthority.model_validate(values)


@pytest.mark.parametrize("namespace", ["", " cloud-a", "cloud-a ", "x" * 256])
@pytest.mark.parametrize(
    "authority_type",
    [WorkerMutationAuthority, AdministrativeMutationCAS],
)
def test_mutation_authority_rejects_invalid_namespace(
    namespace: str,
    authority_type: type[WorkerMutationAuthority] | type[AdministrativeMutationCAS],
) -> None:
    values = {
        "deployment_namespace": namespace,
        "session_id": SessionId(uuid4()),
        "expected_stream_revision": 0,
    }
    if authority_type is WorkerMutationAuthority:
        values["lease_fence"] = _fence()

    with pytest.raises(ValidationError):
        authority_type.model_validate(values)


def test_mutation_authority_accepts_absent_stream_but_rejects_lower_revision() -> None:
    authority = _worker_authority().model_copy(update={"expected_stream_revision": -1})

    assert authority.expected_stream_revision == -1
    with pytest.raises(ValidationError):
        WorkerMutationAuthority.model_validate(
            {**authority.model_dump(), "expected_stream_revision": -2}
        )


def test_stale_worker_authority_is_distinct_and_immutable() -> None:
    authority = _worker_authority()
    variants = (
        authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(
                    update={"control_plane_epoch": uuid4()}
                )
            }
        ),
        authority.model_copy(
            update={"lease_fence": authority.lease_fence.model_copy(update={"fencing_token": 4})}
        ),
        authority.model_copy(
            update={
                "lease_fence": authority.lease_fence.model_copy(
                    update={"owner_instance_id": "worker-b"}
                )
            }
        ),
        authority.model_copy(update={"expected_stream_revision": 8}),
        authority.model_copy(update={"deployment_namespace": "cloud-b"}),
    )

    assert all(candidate != authority for candidate in variants)
    with pytest.raises(ValidationError):
        authority.expected_stream_revision = 8


def test_administrative_cas_is_distinct_from_worker_authority() -> None:
    values = {
        "deployment_namespace": "cloud-a",
        "session_id": SessionId(uuid4()),
        "expected_stream_revision": 2,
    }
    administrative = AdministrativeMutationCAS.model_validate(values)

    assert "lease_fence" not in type(administrative).model_fields
    with pytest.raises(ValidationError):
        AdministrativeMutationCAS.model_validate({**values, "lease_fence": _fence()})
    with pytest.raises(ValidationError):
        WorkerMutationAuthority.model_validate(values)
