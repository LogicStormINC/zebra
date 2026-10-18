"""Legacy command fairness, trusted cancellation and composition regressions."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_storage.postgres.direct_control import PostgresDirectControl
from zebra_agent_config import load_settings
from zebra_agent_worker.command_consumer import SessionCommandConsumer
from zebra_agent_worker.control import SessionControlError, SessionControlService
from zebra_agent_worker.execution_finalization import WorkerExecutionError

from tests.agent_storage.test_command_wakeup import _binding
from tests.worker.test_command_consumer import _command_event, _ExecutionSpy, _seed_session


def _settings():
    return load_settings(env={
        "ZEBRA_PROFILE": "cloud",
        "ZEBRA_LIVE_REDIS_URL": "redis://fixture.invalid:6379/0",
        "ZEBRA_DATABASE_URL": "postgresql://unused:unused@localhost/unused",
        "ZEBRA_RUNTIME_CLASS": "gvisor",
        "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
        "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
    })


def _control(tmp_path, binding, *, kind=SessionCommandKind.STOP):
    stores, session_id, revision = _seed_session(tmp_path)
    direct = Mock(spec=PostgresDirectControl)
    direct.deployment_namespace = "deployment"
    direct.host_scope.return_value = OpaqueAuthorityScope(
        authority_issuer="https://trench.example", namespace_id="tenant-a",
        allowed_session_ids=(str(session_id),),
    )
    service = SessionControlService(
        tmp_path / "unused", settings=_settings(),
        stores=SimpleNamespace(
            events=stores.events, sessions=stores.sessions,
            workspaces=stores.workspaces, deployment_namespace="deployment",
        ),
        cloud_control=direct, command_binding_loader=lambda _: binding,
    )
    command = SessionCommand(
        session_id=session_id, kind=kind,
        expected_revision=revision, idempotency_key="stop",
        payload={"scope": "untrusted", "host_context": {"namespace_id": "evil"}},
    )
    stores.events.append(_command_event(command, revision + 1))
    return service, direct, command


@pytest.mark.parametrize("kind", [SessionCommandKind.STOP, SessionCommandKind.CANCEL])
def test_cancel_uses_binding_and_stable_operation_identity(tmp_path, kind):
    binding = _binding("task")
    service, direct, command = _control(tmp_path, binding, kind=kind)
    service.cancel_command(command)
    service.cancel_command(command)
    assert direct.cancel.call_count == 2
    assert direct.cancel.call_args_list[0] == direct.cancel.call_args_list[1]
    kwargs = direct.cancel.call_args.kwargs
    assert kwargs["operation_id"] == command.command_id
    assert kwargs["idempotency_key"] is None
    assert kwargs["host_context"] == binding.host_capability.host_context
    assert kwargs["scope"] == direct.host_scope.return_value
    assert kwargs["workspace_ref"] == "workspace-a"


@pytest.mark.parametrize("expiry_field", ["grant", "context"])
def test_admitted_cancellation_uses_identity_after_execution_expiry(tmp_path, expiry_field):
    binding = _binding("task")
    expired = datetime.now(UTC) - timedelta(seconds=1)
    host = binding.host_capability
    update = (
        {"grant_expires_at": expired} if expiry_field == "grant"
        else {"host_context": host.host_context.model_copy(update={"expires_at": expired})}
    )
    binding = binding.model_copy(update={"host_capability": host.model_copy(update=update)})
    service, direct, command = _control(tmp_path, binding)
    service.cancel_command(command)
    assert direct.cancel.call_args.kwargs["host_context"] == binding.host_capability.host_context
    assert binding.host_capability == host.model_copy(update=update)


def test_fabricated_or_changed_cancellation_cannot_use_bound_identity(tmp_path):
    from uuid import uuid4

    service, direct, command = _control(tmp_path, _binding("task"))
    with pytest.raises(SessionControlError, match="durable admitted"):
        service.cancel_command(command.model_copy(update={"command_id": uuid4()}))
    with pytest.raises(SessionControlError, match="differs"):
        service.cancel_command(command.model_copy(update={"payload": {"tampered": True}}))
    direct.cancel.assert_not_called()


def test_missing_authority_fails_closed(tmp_path):
    service, direct, command = _control(tmp_path, None)
    with pytest.raises(SessionControlError, match="trusted authority"):
        service.cancel_command(command)
    direct.cancel.assert_not_called()


def test_direct_control_revalidates_binding_scope(tmp_path):
    service, direct, command = _control(tmp_path, _binding("task"))
    direct.host_scope.side_effect = ValueError("Host identity conflicts")
    with pytest.raises(SessionControlError, match="identity conflicts"):
        service.cancel_command(command)
    direct.cancel.assert_not_called()


def test_failures_advance_bounded_pages_and_remain_retryable(tmp_path):
    stores, good_id, revision = _seed_session(tmp_path)
    for _ in range(10):
        _seed_session(tmp_path)
    sessions = sorted(stores.sessions.list_recent_sessions(limit=20), key=lambda s: s.session_id)
    good_id = sessions[-1].session_id
    for session in sessions:
        command = SessionCommand(
            session_id=session.session_id, kind=SessionCommandKind.RUN,
            expected_revision=revision, idempotency_key=str(session.session_id),
        )
        stores.events.append(_command_event(command, revision + 1))
    execution = _ExecutionSpy(stores)
    attempted = []

    def execute(session_id, **kwargs):
        attempted.append(session_id)
        if session_id != good_id:
            raise WorkerExecutionError("retryable command failure")
        execution.execute_session(session_id, **kwargs)

    def page(limit, after):
        return [s for s in sessions if after is None or s.session_id > after][:limit]

    consumer = SessionCommandConsumer(
        stores, SimpleNamespace(execute_session=execute), command_sessions=page,
    )
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "skipped"
    assert len(attempted) == 8
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "executed"
    assert execution.calls == [(good_id, "w", 30)]
    consumer.consume_once(worker_id="w", lease_ttl_seconds=30)  # End of sweep.
    consumer.consume_once(worker_id="w", lease_ttl_seconds=30)
    assert attempted.count(sessions[0].session_id) == 2
    assert stores.sessions.get_session(sessions[0].session_id).current_sequence == revision


def test_payload_cannot_redirect_control_to_another_session(tmp_path):
    stores, session_id, revision = _seed_session(tmp_path)
    _, foreign_id, _ = _seed_session(tmp_path)
    command = SessionCommand(
        session_id=foreign_id, kind=SessionCommandKind.STOP,
        expected_revision=revision, idempotency_key="redirect",
    )
    stores.events.append(_command_event(command, revision + 1).model_copy(
        update={"session_id": session_id},
    ))
    cancel = Mock()
    consumer = SessionCommandConsumer(stores, _ExecutionSpy(stores), cancel_command=cancel)
    assert consumer.consume_once(worker_id="w", lease_ttl_seconds=30).status == "skipped"
    cancel.assert_not_called()


def test_async_cancellation_is_not_a_skipped_command(tmp_path):
    stores, session_id, revision = _seed_session(tmp_path)
    command = SessionCommand(
        session_id=session_id, kind=SessionCommandKind.STOP,
        expected_revision=revision, idempotency_key="cancel",
    )
    stores.events.append(_command_event(command, revision + 1))
    consumer = SessionCommandConsumer(
        stores, _ExecutionSpy(stores), cancel_command=Mock(side_effect=asyncio.CancelledError),
    )
    with pytest.raises(asyncio.CancelledError):
        consumer.consume_once(worker_id="w", lease_ttl_seconds=30)
    assert stores.sessions.get_session(session_id).current_sequence == revision


@pytest.mark.parametrize("migrated", [False, True])
def test_cloud_loop_composes_control_without_changing_cutover(tmp_path, monkeypatch, migrated):
    from zebra_agent_worker.cloud_composition import compose_cloud_worker
    from zebra_agent_worker.loop import build_worker_loop_service

    from tests.test_cloud_api_worker_profile_composition import _cloud_settings

    monkeypatch.setattr("agent_storage.runtime_composition.require_current_schema", lambda _: None)
    bundle = compose_cloud_worker(_cloud_settings())
    monkeypatch.setattr(
        "zebra_agent_worker.command_process_state.command_cutover_state", lambda *a, **kw: migrated,
    )
    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", lambda **kw: Mock())
    service = build_worker_loop_service(
        database_path=tmp_path / "unused", settings=_settings(), cloud_worker_composition=bundle,
    )
    assert service._stream_hint_relay is not None
    service.drain()
    assert (service.migrated_run is not None) == migrated
    consumer = service._command_consumer
    if migrated:
        assert consumer is None
    else:
        assert consumer._command_sessions is not None
        control = consumer._control_service
        assert isinstance(control._cloud_control, PostgresDirectControl)
        assert control._cloud_control.deployment_namespace == bundle.deployment_namespace
        assert control._cloud_control._database._dsn == bundle.dsn
        assert control._command_binding_loader is not None
        assert consumer._cancel_command == control.cancel_command
