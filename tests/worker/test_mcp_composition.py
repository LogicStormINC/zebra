"""Startup and durable Turn authority checks, with no production network access."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteEventStore
from zebra_agent_config.mcp_credentials import load_mcp_credentials
from zebra_agent_worker import mcp_composition

from tests.api import test_mcp_credential_composition as credentials
from tests.worker import test_extension_recovery as recovery
from tests.worker import test_worker_mcp_catalog as execution

protector = execution.protector
mounted = credentials.mounted


def test_worker_setting_default_and_disabled_composition(mounted):
    assert not load_mcp_credentials({}).worker_enabled
    assert load_mcp_credentials({"ZEBRA_CLOUD_MCP_WORKER_ENABLED": "true"}).worker_enabled
    assert mcp_composition.compose_worker_mcp(mounted, None) is None


def test_api_execution_requires_turn_admission(mounted):
    from zebra_agent_api.extension_composition import compose_http_turn_admission

    settings = replace(
        mounted, mcp_credentials=replace(mounted.mcp_credentials, worker_enabled=True),
    )
    with pytest.raises(ValueError, match="Turn admission"):
        compose_http_turn_admission(settings, Mock(), None)


def test_worker_composes_from_same_cloud_bundle(mounted):
    settings = replace(mounted, cloud_extension_worker_enabled=True,
                       mcp_credentials=replace(mounted.mcp_credentials, worker_enabled=True))
    cloud = Mock(dsn="postgresql://unused", deployment_namespace="test")
    source = mcp_composition.compose_worker_mcp(settings, cloud)
    assert source.leases is cloud.stores.leases
    assert source.release.snapshots is cloud.extension_snapshots
    assert source.release.tasks is cloud.extension_snapshots
    assert source.release.store is source.connections
    source.release.protector.validate_active_key()
    cloud.stores.events.list_for_session.assert_not_called()


@pytest.mark.parametrize("change", ["local", "recovery", "bundle", "dsn", "snapshots", "key"])
def test_worker_incomplete_startup_rejected(mounted, change):
    settings = replace(mounted, cloud_extension_worker_enabled=True,
                       mcp_credentials=replace(mounted.mcp_credentials, worker_enabled=True))
    cloud = Mock(dsn="postgresql://unused", deployment_namespace="test")
    if change == "local":
        settings = replace(settings, profile="local")
    elif change == "recovery":
        settings = replace(settings, cloud_extension_worker_enabled=False)
    elif change == "bundle":
        cloud = None
    elif change == "key":
        settings = replace(
            settings, mcp_credentials=replace(settings.mcp_credentials, key_handle="missing"),
        )
    else:
        setattr(cloud, "extension_snapshots" if change == "snapshots" else "dsn", None)
    with pytest.raises(ValueError):
        mcp_composition.compose_worker_mcp(settings, cloud)


def test_durable_authority_requires_current_turn_and_live_evidence(tmp_path, protector):
    callback, _, _ = execution.setup(tmp_path, protector)
    evidence = execution.worker_authority(callback)
    _, _, seed = recovery._fixtures()
    turn_id = seed[-1].payload["turn_id"]
    store = SQLiteEventStore(tmp_path / "events.db")
    message = seed[-1].model_copy(update={"session_id": callback.session_id, "sequence": 1})
    store.append(message)
    with pytest.raises(ValueError, match="no durable"):
        mcp_composition.load_worker_mcp_authority(store, callback.session_id, turn_id)
    store.append(SessionEvent.create(
        session_id=callback.session_id, sequence=2,
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED, actor=EventActor.SYSTEM,
        payload=evidence.snapshot.to_event_payload(),
    ))
    actual = mcp_composition.load_worker_mcp_authority(store, callback.session_id, turn_id)
    assert actual == evidence
    with pytest.raises(ValueError, match="current Turn"):
        mcp_composition.load_worker_mcp_authority(store, callback.session_id, "other-turn")
    store.append(SessionEvent.create(
        session_id=callback.session_id, sequence=3,
        event_type=EventType.TURN_COMPLETED, actor=EventActor.HARNESS,
        payload={"turn_id": turn_id, "turn_index": 1, "summary": "done"},
    ))
    with pytest.raises(ValueError):
        mcp_composition.load_worker_mcp_authority(store, callback.session_id, turn_id)
