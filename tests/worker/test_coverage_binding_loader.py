"""Actual Worker accepts fresh, read-only native Session binding composition."""
# ruff: noqa: F811

from dataclasses import replace

import pytest
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.task_admission import load_session_task_binding
from zebra_agent_config.coverage_settings import CoverageWorkSettings

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_dispatch import (  # noqa: F401
    _stop_native_capability,
    native_handoff,
    native_worker,
)


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
def test_worker_certifies_with_fresh_native_binding_loader(native_worker):
    env = native_worker
    reads = []

    def binding(session):
        result = load_session_task_binding(
            env.dsn, deployment_namespace=NAMESPACE, session_id=session
        )
        reads.append(result.binding_digest)
        return result

    env.service._task_binding_loader = binding
    env.reply_from_request = True
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000)
    )
    _stop_native_capability(env, remove_revoked=True)
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    assert len(reads) > 1 and set(reads) == {env.task_binding.binding_digest}
