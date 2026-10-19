"""Native component sources retain their existing Cloud identity and checks."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_runtime.mcp_protocol import McpProtocolError
from agent_tools import McpProxyRequest, McpToolTarget
from agent_tools.cloud_skills import CloudSkillCatalog
from zebra_agent_worker.plugin_composition import compose_worker_plugins
from zebra_agent_worker.worker_mcp_catalog import prepare_worker_mcp
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)

from tests.worker.test_cloud_skill_wiring import Backend, _extension
from tests.worker.test_worker_mcp_catalog import protector, setup, wire

__all__ = ["protector", "wire"]


def test_worker_composition_has_no_bundle_mount_or_mcp_secret_requirement() -> None:
    off = SimpleNamespace(plugins=SimpleNamespace(enabled=False))
    assert compose_worker_plugins(off, None) is None
    settings = SimpleNamespace(
        plugins=SimpleNamespace(enabled=True),
        deployment="cloud",
        storage_authority="postgresql",
        cloud_extension_worker_enabled=True,
    )
    cloud = SimpleNamespace(
        dsn="postgresql://unused",
        deployment_namespace="plugins",
        extension_snapshots=Mock(),
        skill_objects=Mock(),
        stores=SimpleNamespace(task_io_connections=None),
    )
    source = compose_worker_plugins(settings, cloud)
    assert source.packages.objects is cloud.skill_objects
    assert not cloud.skill_objects.mock_calls


def test_guarded_skill_catalog_preserves_native_identity_and_authorization() -> None:
    backend, guard = Backend(), Mock()
    catalog = prepare_worker_skill_catalog(
        _extension(backend),
        deployment_namespace="test",
        source=WorkerSkillCatalogSource(backend, backend),
        plugin_guard=guard,
    )
    assert isinstance(catalog, CloudSkillCatalog)
    assert catalog.list()[0][0].name == "sample"
    assert guard.validate.call_count == 2 and backend.calls == ["authorization"]
    guard.validate.side_effect = PluginAuthorityUnavailable()
    with pytest.raises(PluginAuthorityUnavailable):
        catalog.read("sample")
    assert "object" not in backend.calls


def test_mcp_per_frame_plugin_stop_and_native_lease_priority(tmp_path, protector, wire) -> None:
    callback, source, extension = setup(tmp_path, protector)
    guard = Mock()
    guard.validate.side_effect = PluginAuthorityUnavailable()
    transport = prepare_worker_mcp(
        extension,
        source=source,
        session_id=callback.session_id,
        fence=callback.fence,
        plugin_guard=guard,
    )
    assert transport.model_tools
    _, server, tool = transport.model_tools[0].name.split(".")
    with pytest.raises(PluginAuthorityUnavailable):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    assert wire == [] and guard.validate.call_count == 1
    guard.reset_mock()
    callback.leases.release(callback.session_id, fence=callback.fence)
    with pytest.raises(McpProtocolError):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    guard.validate.assert_not_called()


def _shared_extension(extension, kind, identifier):
    from agent_core.domain.extension_snapshots import ExtensionSnapshot
    from agent_core.domain.plugin_snapshots import PluginComponentSource, PluginSnapshot
    from zebra_agent_worker.extension_recovery import RecoveredTurnExtension

    from tests.agent_storage.test_postgres_plugin_installations import _record

    pin = PluginSnapshot.from_installation(_record(enabled=True)).model_copy(
        update={
            "components": (
                PluginComponentSource(component_id="test-mcp", kind=kind, target_id=identifier),
            )
        }
    )
    snapshot = ExtensionSnapshot.model_validate(
        {
            **extension.snapshot.model_dump(),
            "plugins": (pin,),
            "direct_skills" if kind == "skill-bundle" else "direct_mcp": (identifier,),
        }
    )
    return RecoveredTurnExtension(extension.scope, snapshot, extension.task_ceiling)


def _shared_guard(extension):
    from unittest.mock import AsyncMock

    from zebra_agent_worker.worker_plugins import WorkerPluginGuard, WorkerPluginSource

    source = WorkerPluginSource(AsyncMock(), AsyncMock())
    return WorkerPluginGuard(source, extension, ())


@pytest.mark.parametrize("bearer", [False, True])
def test_shared_mcp_native_revision_conflict_is_plugin_stop(
    tmp_path, protector, wire, bearer
) -> None:
    from agent_core.domain.extensions import McpAuthMode, McpAuthState
    from agent_core.ports.extensions import ExtensionRevisionConflictError

    callback, source, extension = setup(tmp_path, protector)
    if bearer:
        entry = extension.snapshot.mcp[0]
        connection = entry.connection.model_copy(
            update={
                "auth_mode": McpAuthMode.BEARER,
                "auth_state": McpAuthState.READY,
                "credential_ref": "credential",
            }
        )
        catalog = source.catalogs.get.return_value.model_copy(update={"connection": connection})
        source.catalogs.get.return_value = catalog
        snapshot = extension.snapshot.model_copy(
            update={
                "mcp": (
                    entry.model_copy(
                        update={"connection": connection, "catalog_digest": catalog.digest}
                    ),
                )
            }
        )
        extension = type(extension)(extension.scope, snapshot, extension.task_ceiling)
        source.release.store.get_for_use.side_effect = ExtensionRevisionConflictError(
            "private conflict"
        )
    else:
        source.connections.get_connection.side_effect = ExtensionRevisionConflictError(
            "private conflict"
        )
    extension = _shared_extension(
        extension, "mcp-http", extension.snapshot.mcp[0].connection.connection_id
    )
    source.release.snapshots.get.return_value = extension.snapshot
    guard = _shared_guard(extension)
    transport = prepare_worker_mcp(
        extension,
        source=source,
        session_id=callback.session_id,
        fence=callback.fence,
        plugin_guard=guard,
    )
    _, server, tool = transport.model_tools[0].name.split(".")
    with pytest.raises(PluginAuthorityUnavailable):
        transport.execute(McpProxyRequest("call", McpToolTarget(server, tool)))
    assert wire == [] and not guard.source.installations.mock_calls
    operation = McpProxyRequest("call", McpToolTarget(server, tool))
    entry = extension.snapshot.mcp[0]
    with pytest.raises(McpProtocolError):
        transport._authorize(
            entry,
            operation,
            entry.connection.endpoint,
            {"method": "tools/call", "params": {"name": "unrequested", "arguments": {}}},
        )
    callback.leases.release(callback.session_id, fence=callback.fence)
    with pytest.raises(McpProtocolError):
        transport.execute(operation)
    assert wire == []


def test_shared_skill_native_authority_loss_suspends_serial_without_next_model() -> None:
    from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
    from agent_core.domain.modeling import ModelToolDefinition
    from agent_core.harness import (
        HarnessAttemptOutcome,
        HarnessLoop,
        HarnessModelStep,
        HarnessTask,
        SingleAttemptOrchestrator,
    )
    from agent_tools.skills import SkillsReadTool

    from tests.agent_core.test_concurrent_tool_batches import (
        NOW,
        PolicyByProviderId,
        _call,
        _completion,
    )

    backend = Backend()
    extension = _shared_extension(
        _extension(backend), "skill-bundle", backend.installation.installation_id
    )
    guard = _shared_guard(extension)
    catalog = prepare_worker_skill_catalog(
        extension,
        deployment_namespace="test",
        source=WorkerSkillCatalogSource(backend, backend),
        plugin_guard=guard,
    )
    tool = SkillsReadTool(catalog)
    assert catalog.read("sample").content
    missing = tool.handle(
        _call(
            "skills.read", {"name": "sample", "file_path": "references/missing.txt"}, "missing-file"
        )
    )
    assert missing.status.value == "failed"
    backend.installation = backend.installation.model_copy(update={"enabled": False})
    call = _call("skills.read", {"name": "sample"}, "shared-skill")
    model = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(completion=_completion("Read", call)),
            ScriptedModelResponse(completion=_completion("must not run")),
        )
    )
    gateway = SimpleNamespace(execute=tool.handle, read_only_tools=frozenset({"skills.read"}))
    result = HarnessLoop().run(
        HarnessTask(title="Shared Skill", user_input="Read", max_model_calls=2),
        SingleAttemptOrchestrator(
            model,
            PolicyByProviderId(),
            gateway,
            model_step=HarnessModelStep(
                available_tools=(
                    ModelToolDefinition(
                        name="skills.read",
                        description="Read",
                        parameters={"type": "object", "properties": {}},
                    ),
                )
            ),
            synthesize_tool_results=True,
        ).run,
        created_at=NOW,
    )
    assert result.attempt_result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert len(model.requests) == 1
    assert not guard.source.installations.mock_calls
