"""Preparation cannot masquerade as transient failure or busy-loop on a missing index."""

from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.leases import LeaseFence, LeaseLostError, WorkerLease
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from agent_core.ports.worker_preparation import PreparationAdvanced
from zebra_agent_worker.execution_preparation import finish_preparation
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat


def test_preparation_handoff_renews_latest_checkpoint_without_releasing_lease():
    now = datetime.now(UTC)
    lease = WorkerLease(
        session_id=uuid4(),
        fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="prepare"),
        checkpoint=0,
        acquired_at=now,
        heartbeat_at=now,
        expires_at=now + timedelta(seconds=3),
    )
    resumed = Event()
    checkpoints = []

    def renew(current, *, lease_ttl_seconds, checkpoint=None):
        value = current.checkpoint if checkpoint is None else checkpoint
        assert not checkpoints or value >= checkpoints[-1]
        checkpoints.append(value)
        if len(checkpoints) >= 2:
            resumed.set()
        return current.model_copy(update={"checkpoint": value})

    claims = Mock()
    claims.heartbeat_lease.side_effect = renew
    heartbeat = LeaseHeartbeat(claims, lease, lease_ttl_seconds=3, release_on_exit=False)
    heartbeat._interval_seconds = 0.01
    with heartbeat:
        assert heartbeat.advance_checkpoint(100).checkpoint == 100
        assert resumed.wait(1)
        heartbeat.require_owned()
    assert checkpoints[0] == 100
    claims.release_lease.assert_not_called()


def test_progress_keeps_one_operation_and_one_lease_until_ready():
    operation = Mock(
        side_effect=[
            PreparationAdvanced("input:v1", 255, 999),
            PreparationAdvanced("input:v1", 511, 999),
            PreparationAdvanced("indexes:v1", 255, 999),
            "ready",
        ]
    )
    ownership = Mock()
    assert finish_preparation(operation, ownership) == "ready"
    assert operation.call_count == ownership.call_count == 4


def test_dependency_not_ready_is_not_retried():
    operation = Mock(side_effect=CheckpointNotReady("missing Task identity"))
    with pytest.raises(CheckpointNotReady, match="missing Task"):
        finish_preparation(operation, Mock())
    assert operation.call_count == 1


@pytest.mark.parametrize("position,highwater", [(255, 999), (254, 999), (256, 998)])
def test_no_progress_or_source_regression_cannot_spin(position, highwater):
    operation = Mock(
        side_effect=[
            PreparationAdvanced("input:v1", 255, 999),
            PreparationAdvanced("input:v1", position, highwater),
        ]
    )
    with pytest.raises(ValueError, match="did not advance"):
        finish_preparation(operation, Mock())
    assert operation.call_count == 2


def test_cancel_or_expired_lease_stops_before_next_slice():
    operation = Mock(side_effect=PreparationAdvanced("input:v1", 255, 999))
    ownership = Mock(side_effect=[None, LeaseLostError("cancelled")])
    with pytest.raises(LeaseLostError):
        finish_preparation(operation, ownership)
    assert operation.call_count == 1


@pytest.mark.parametrize(
    "key,position,highwater",
    [
        ("", 1, 2),
        ("input", True, 2),
        ("input", 1, True),
        ("input", -1, 2),
        ("input", 3, 2),
    ],
)
def test_invalid_progress_fails_before_any_retry(key, position, highwater):
    with pytest.raises(ValueError, match="invalid durable"):
        PreparationAdvanced(key, position, highwater)
