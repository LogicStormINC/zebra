"""Tool threads inherit bounds and identity, not another thread's database connection."""

from contextvars import ContextVar
from time import monotonic

from agent_core.harness import HarnessAttemptOutcome
from agent_storage.postgres.connection_scope import (
    current_connection_scope,
    postgres_connection_scope,
)
from agent_storage.postgres.database import current_postgres_deadline, postgres_deadline
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline

from tests.agent_core.test_concurrent_tool_batches import ProbeGateway, _read, _run


def test_each_parallel_call_inherits_its_own_context_and_bounds() -> None:
    identity: ContextVar[str] = ContextVar("probe_identity", default="missing")
    deadline = monotonic() + 10
    observations = []

    class ScopedGateway(ProbeGateway):
        def execute(self, call):
            observations.append((identity.get(), current_task_io_deadline(),
                                 current_postgres_deadline(), current_connection_scope()))
            identity.set(call.provider_call_id)
            result = super().execute(call)
            assert identity.get() == call.provider_call_id
            return result

    token = identity.set("request-A")
    try:
        with task_io_deadline(deadline), postgres_deadline(deadline), postgres_connection_scope():
            assert current_connection_scope() is not None
            result, _ = _run((_read("a", "call_a"), _read("b", "call_b")),
                             ScopedGateway(), max_parallel=2)
        assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
        assert observations == [("request-A", deadline, deadline, None)] * 2
        assert identity.get() == "request-A"
    finally:
        identity.reset(token)
