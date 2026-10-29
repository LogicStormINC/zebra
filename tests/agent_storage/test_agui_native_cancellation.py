"""Optional cancellation preparation runs under the actual native transaction."""

from uuid import uuid4

import pytest
from agent_core.domain.client_preparation import ClientPreparationContext
from agent_core.domain.events import EventType

from tests.agent_storage.test_postgres_direct_control import (
    _cancel,
    _rows,
)
from tests.agent_storage.test_postgres_direct_control import (
    dsn as _dsn,
)
from tests.agent_storage.test_postgres_direct_control import (
    postgres_dsn as postgres_dsn,
)
from tests.agent_storage.test_postgres_runtime_instances import _setup

dsn = _dsn


def test_native_cancel_authority_failure_keeps_original_lease_and_events(dsn):
    lease = _setup(dsn)
    context = ClientPreparationContext(
        operation_id=uuid4(),
        client_session_id=uuid4(),
        task_id=lease.session_id,
        run_id="native",
        projection_version="test:r2",
        request_hash="a" * 64,
        input={},
        previous_run_id="agui:" + "b" * 64,
    )
    before = _rows(dsn, "session_events")
    leases = _rows(dsn, "worker_leases")

    def deny():
        raise ValueError("current controller changed")

    with pytest.raises(ValueError, match="current controller changed"):
        _cancel(
            dsn,
            lease.session_id,
            operation_id=context.operation_id,
            preparation=context,
            authorize_preparation=deny,
        )
    assert _rows(dsn, "session_events") == before
    assert _rows(dsn, "worker_leases") == leases


def test_native_cancel_captures_private_input_on_actual_terminal_once(dsn):
    lease = _setup(dsn)
    operation = uuid4()
    context = ClientPreparationContext(
        operation_id=operation,
        client_session_id=uuid4(),
        task_id=lease.session_id,
        run_id="native",
        projection_version="test:r2",
        request_hash="a" * 64,
        input={"messages": []},
        previous_run_id="agui:" + "b" * 64,
    )
    seen = []

    def authorize():
        seen.append(True)

    result = _cancel(
        dsn,
        lease.session_id,
        operation_id=operation,
        preparation=context,
        authorize_preparation=authorize,
    )
    assert seen == [True]
    assert result.event.event_type is EventType.SESSION_CANCELLED
    assert result.event.payload["input"] == context.input
    assert result.event.payload["client_preparation"] == context.model_dump(
        mode="json", exclude={"input"}
    )
    before = _rows(dsn, "session_events")
    assert _cancel(dsn, lease.session_id, operation_id=operation) == result
    assert _rows(dsn, "session_events") == before
    assert _rows(dsn, "worker_leases")[0]["released_at"] is not None
