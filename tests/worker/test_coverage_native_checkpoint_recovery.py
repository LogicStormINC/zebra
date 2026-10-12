"""A replacement Worker recovers uploaded staged bytes, never repeats MODEL HTTP."""
# ruff: noqa: F401,F811

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.command_wakeup_recovery import RecoveryStatus, recover_command_batch
from zebra_agent_config.coverage_settings import CoverageWorkSettings

from tests.worker.coverage_model_cloud_fixtures import NAMESPACE, dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("mutation", ["none", "missing", "corrupt", "stop"])
def test_replacement_recovers_staged_checkpoint_through_actual_worker(
    native_worker, monkeypatch, mutation,
):
    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    uploaded = []
    put = env.client.put_object

    def crash_after_put(**kwargs):
        result = put(**kwargs)
        try:
            body = json.loads(kwargs["Body"])
        except (ValueError, UnicodeError):
            return result
        if (isinstance(body, dict)
                and body.get("schema", "").startswith("coverage-model-checkpoint/")):
            uploaded.append(kwargs["Key"])
            raise KeyboardInterrupt("worker lost after checkpoint PUT")
        return result

    handoff = native_handoff(env)
    with monkeypatch.context() as patch:
        patch.setattr(env.client, "put_object", crash_after_put)
        with pytest.raises(KeyboardInterrupt, match="worker lost"):
            env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert len(uploaded) == 1
    assert sum(request.url.path == "/chat/completions" for request in env.native_requests) == 1
    if mutation == "missing":
        del env.client.objects[uploaded[0]]
    elif mutation == "corrupt":
        item = env.client.objects[uploaded[0]]
        item["Body"] = b"x" * len(item["Body"])
    elif mutation == "stop":
        history = env.events.list_for_session(env.session)
        env.events.append(SessionEvent.create(
            session_id=env.session, sequence=history[-1].sequence + 1,
            event_type=EventType.SESSION_CANCELLED, actor=EventActor.SYSTEM,
            created_at=datetime.now(UTC), payload={"reason": "test revocation"},
        ))
    # This is exceptional crash recovery, not a normal continuation or a second command.
    with env.database.connect() as connection:
        connection.execute(
            "UPDATE session_command_pending SET recovery_due_at=clock_timestamp() "
            "WHERE deployment_namespace=%s AND session_id=%s AND status='pending'",
            (NAMESPACE, env.session),
        )
    recovery = recover_command_batch(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
        coverage_check=env.native_checker,
    )
    if mutation != "none":
        assert not any(item.status is RecoveryStatus.APPROVED for item in recovery), recovery
        assert not any(event.event_type is EventType.COVERAGE_REPORT_CERTIFIED
                       for event in env.events.list_for_session(env.session))
        assert sum(request.url.path == "/chat/completions" for request in env.native_requests) == 1
        return
    assert any(item.status is RecoveryStatus.APPROVED for item in recovery), recovery
    replacement = native_handoff(env)
    assert replacement.lease is not None, replacement
    result = env.service.execute_claimed_session(replacement.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    assert sum(request.url.path == "/chat/completions" for request in env.native_requests) == 1
