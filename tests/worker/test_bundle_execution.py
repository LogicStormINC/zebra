"""Actual task bootstrap, durable recovery and Worker/provider execution."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.bundle_definition import snapshot_from_version
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_worker import (
    SessionClaimService,
    SessionExecutionService,
    SessionRecoveryService,
    SessionResumeService,
)
from zebra_agent_worker.bundle_assembly import require_task_compatibility
from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError

from tests.agent_core.test_bundle_definition import bundle_version
from tests.test_bundle_assembly import approved_assembly, settings, write_catalog

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def seed(tmp_path, assembly, *, coverage=False):
    from tests.worker.test_coverage_task_recovery import context, identity

    scope = assembly.bundle.manifest.scope
    version = bundle_version(
        runtime_assembly=assembly,
        authority_issuer=scope.authority_issuer,
        namespace_id=scope.namespace_id,
    )
    snapshot = snapshot_from_version(version=version, resolved_at=NOW)
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Frozen bundle task",
            user_input="Reply with one short sentence.",
            workspace_root=tmp_path,
            definition_snapshot=snapshot,
            tool_profile=ToolProfile.CODING,
            network_profile="none",
            coverage_admission=identity() if coverage else None,
            host_context=context() if coverage else None,
        )
    )
    database = tmp_path / "worker.db"
    events = SQLiteEventStore(database)
    for event in boot.events:
        events.append(event)
    SQLiteProjectionStore(database).save_session(boot.session)
    return boot.session.session_id, snapshot


def worker(database, configured, client=None):
    claim = SessionClaimService(
        SQLiteLeaseStore(database),
        SessionRecoveryService(
            SQLiteEventStore(database),
            SQLiteProjectionStore(database),
            SQLiteWorkspaceProjectionStore(database),
        ),
    )
    return SessionExecutionService(
        database_path=database,
        claim_service=claim,
        resume_service=SessionResumeService(claim),
        settings=configured,
        model_http_client=client,
    )


def reply(request, bodies):
    body = json.loads(request.content)
    bodies.append(body)
    if body["stream"]:
        events = [
            {
                "choices": [
                    {"index": 0, "delta": {"content": "Bound reply."}, "finish_reason": None}
                ]
            },
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n",
        )
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Bound reply."},
                    "finish_reason": "stop",
                }
            ]
        },
    )


def test_actual_worker_recovers_original_snapshot_after_current_profile_change(
    tmp_path, monkeypatch
):
    database = tmp_path / "worker.db"
    base = replace(settings(), database_url=str(database))
    assembly, configured, catalog = write_catalog(tmp_path, base)
    sid, snapshot = seed(tmp_path, assembly)
    # A new catalog/provider/default model is not the task's configuration authority.
    from agent_core.domain.runtime_assembly import canonical_provider_profile_digest

    replacement, _ = approved_assembly(base, model="beta")
    profile = replacement.provider_profile.model_dump(mode="json")
    profile["models"] = ["beta"]
    profile["pin"]["digest"] = canonical_provider_profile_digest(profile)
    catalog["providers"] = [profile]
    Path(configured.runtime_bundle_config).write_text(json.dumps(catalog))
    configured = replace(configured, model=replace(configured.model, model="new-default"))
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    bodies = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: reply(request, bodies))
    ) as client:
        result = worker(database, configured, client).execute_session(
            sid, worker_id="bundle-worker"
        )
    assert result.session.status is SessionStatus.COMPLETED
    assert bodies and all(body["model"] == "alpha" for body in bodies)
    assert any("Frozen business alpha." in json.dumps(body["messages"]) for body in bodies)
    assert all(body["max_tokens"] <= 2048 and body["temperature"] == 0.25 for body in bodies)
    events = SQLiteEventStore(database).list_for_session(sid)
    prepared = next(e for e in events if e.event_type.value == "task_prepared")
    assert prepared.payload["definition_snapshot"] == snapshot.model_dump(mode="json")
    assert "private-key" not in json.dumps([event.payload for event in events])
    restored = SQLiteWorkspaceProjectionStore(database).get_workspace(sid)
    assert restored.definition_snapshot == snapshot


def test_actual_incompatible_worker_refuses_before_provider_or_runtime(tmp_path, monkeypatch):
    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, _ = seed(tmp_path, assembly)
    changed = replace(configured, cloud_extension_worker_enabled=True)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda *args, **kwargs: pytest.fail("process default model used"),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.runtime_setup.prepare_runtime",
        lambda *args, **kwargs: pytest.fail("runtime started"),
        raising=False,
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("provider called"))
    ) as client:
        with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
            service = worker(database, changed, client)
            service._workspace_resolver = SimpleNamespace(
                resolve=lambda *args, **kwargs: pytest.fail("workspace provisioned")
            )
            service.execute_session(sid, worker_id="incompatible-worker")
    assert SQLiteProjectionStore(database).get_session(sid).status is SessionStatus.READY
    # A matching worker can acquire and finish the same durable task afterwards.
    monkeypatch.undo()
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    bodies = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: reply(request, bodies))
    ) as client:
        result = worker(database, configured, client).execute_session(
            sid, worker_id="matching-worker"
        )
    assert result.session.status is SessionStatus.COMPLETED
    assert bodies and all(body["model"] == "alpha" for body in bodies)


def test_v2_coverage_and_policy_overrides_are_refused_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    assembly, configured, _ = write_catalog(tmp_path, settings())
    scope = assembly.bundle.manifest.scope
    snapshot = snapshot_from_version(
        version=bundle_version(
            runtime_assembly=assembly,
            authority_issuer=scope.authority_issuer,
            namespace_id=scope.namespace_id,
        ),
        resolved_at=NOW,
    )
    task = SimpleNamespace(
        definition_snapshot=snapshot, coverage_admission=object(), model_invocation_policy=None
    )
    with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
        require_task_compatibility(configured, task)


def test_legacy_task_does_not_require_execution_catalog():
    require_task_compatibility(settings(), SimpleNamespace(definition_snapshot=None))


def test_pending_durable_close_is_healed_before_incompatible_worker_check(tmp_path, monkeypatch):
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.turns import derive_turn_id

    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, _ = seed(tmp_path, assembly)
    events = SQLiteEventStore(database)
    initial = events.list_for_session(sid)
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (
            EventType.TURN_COMPLETED,
            {
                "turn_id": str(derive_turn_id(sid, 0)),
                "turn_index": 0,
                "summary": "durable result",
                "closes_segment": True,
            },
        ),
    ):
        events.append(
            SessionEvent.create(
                session_id=sid,
                sequence=events.list_for_session(sid)[-1].sequence + 1,
                event_type=kind,
                actor=EventActor.HARNESS,
                payload=payload,
            )
        )
    monkeypatch.setattr(
        "zebra_agent_worker.bundle_assembly.require_task_compatibility",
        lambda *args: pytest.fail("compatibility preceded durable close healing"),
    )
    result = worker(database, replace(configured, runtime_bundle_config=None)).execute_session(
        sid, worker_id="close-healing-worker"
    )
    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.summary == "durable result"
    assert len(initial) < len(events.list_for_session(sid))


def test_concurrent_tasks_share_worker_without_configuration_bleed(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    database = tmp_path / "worker.db"
    base = replace(settings(), database_url=str(database))
    alpha, configured, _ = write_catalog(tmp_path, base)
    beta, _ = approved_assembly(base, model="beta")
    ids = [seed(tmp_path, assembly)[0] for assembly in (alpha, beta)]
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    bodies = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: reply(request, bodies))
    ) as client:
        service = worker(database, configured, client)

        def execute(sid):
            return service.execute_session(sid, worker_id="parallel-" + str(sid))

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, ids))
    assert all(result.session.status is SessionStatus.COMPLETED for result in results)
    for model in ("alpha", "beta"):
        matching = [body for body in bodies if body["model"] == model]
        assert matching and any(
            f"Frozen business {model}." in json.dumps(body) for body in matching
        )
        other = "beta" if model == "alpha" else "alpha"
        assert all(f"Frozen business {other}." not in json.dumps(body) for body in matching)
    assert service._settings == configured


@pytest.mark.parametrize("strict_runtime", [False, True])
def test_actual_worker_refuses_bound_coverage_before_dispatch(
    tmp_path, strict_runtime, monkeypatch
):
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, _ = seed(tmp_path, assembly, coverage=True)
    service = worker(database, configured)
    if strict_runtime:
        service._coverage_runtime = SimpleNamespace(
            execute=lambda *args: pytest.fail("Coverage dispatched")
        )
    with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
        service.execute_session(sid, worker_id="unsupported-coverage-worker")
    assert SQLiteProjectionStore(database).get_session(sid).status is SessionStatus.READY


def test_incompatible_bundle_refuses_before_setup_only_terminal_failure(tmp_path):
    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, _ = seed(tmp_path, assembly)
    # Recovered network profile is supplied by the task; force the unsupported
    # capability branch while keeping the persisted bundle unchanged.
    from unittest.mock import patch

    import zebra_agent_worker.execution as execution
    from agent_core.domain.networking import NetworkProfileName
    from agent_security import NetworkProfile

    prepare = execution.prepare_execution_inputs

    def setup_only(*args, **kwargs):
        inputs = prepare(*args, **kwargs)
        return replace(
            inputs,
            task=replace(
                inputs.task, network_profile=NetworkProfile(name=NetworkProfileName.SETUP_ONLY)
            ),
        )

    service = worker(database, replace(configured, runtime_bundle_config=None))
    service._artifact_payload_store = None
    with patch.object(execution, "prepare_execution_inputs", setup_only):
        with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
            service.execute_session(sid, worker_id="setup-only-worker")
    assert SQLiteProjectionStore(database).get_session(sid).status is SessionStatus.READY


def test_missing_provider_credential_refuses_before_workspace_materialization(
    tmp_path, monkeypatch
):
    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, _ = seed(tmp_path, assembly)
    monkeypatch.delenv("BUNDLE_MODEL_KEY", raising=False)
    service = worker(database, configured)
    service._workspace_resolver = SimpleNamespace(
        resolve=lambda *args, **kwargs: pytest.fail(
            "workspace provisioned without provider credential"
        )
    )
    with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
        service.execute_session(sid, worker_id="credential-unavailable")
    assert SQLiteProjectionStore(database).get_session(sid).status is SessionStatus.READY


@pytest.mark.parametrize(
    "local_extension",
    [
        "skill_roots",
        "skill_roots_system",
        "skill_roots_admin",
        "skill_roots_repo",
        "mcp",
    ],
)
def test_unversioned_local_extensions_cannot_hide_behind_matching_baseline(
    tmp_path,
    monkeypatch,
    local_extension,
):
    from zebra_agent_config.bundle_settings import baseline_digest
    from zebra_agent_config.settings import McpServerSettings

    database = tmp_path / "worker.db"
    base = replace(settings(), database_url=str(database))
    if local_extension != "mcp":
        base = replace(base, **{local_extension: (str(tmp_path / "mutable-skills"),)})
    else:
        base = replace(
            base, mcp_servers=(McpServerSettings(name="mutable", command="/bin/echo", args=()),)
        )
    assembly, configured, _ = write_catalog(tmp_path, base)
    assert assembly.bundle.manifest.baseline_config.digest == baseline_digest(configured, "ab" * 32)
    sid, _ = seed(tmp_path, assembly)
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("unversioned extension reached model")
            )
        ) as client:
            worker(database, configured, client).execute_session(
                sid, worker_id="unversioned-extension-worker"
            )
    assert SQLiteProjectionStore(database).get_session(sid).status is SessionStatus.READY
