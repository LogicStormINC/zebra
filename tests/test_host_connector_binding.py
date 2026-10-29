"""A frozen manifest must pin its real connector, not an unbound placeholder."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.host_connectors import HostConnectorProfileVersion
from zebra_agent_api.host_manifest_freeze import HostManifestFreezeError, resolve_admission_profile
from zebra_agent_api.session_binding import _build_binding_snapshot

from tests.api.test_session_binding_renewal import _context, _verified


def profile():
    return HostConnectorProfileVersion(
        host_app_id="trench",
        connector_id="a-real-connector",
        profile_revision=3,
        base_uri="https://connector.example",
        manifest_path="/manifest",
        invoke_path_template="/invoke",
        supported_protocol_versions=("v1",),
        workload_identity_ref="worker",
        credential_ref="reference-one",
    )


def test_builder_retains_real_pin_and_renewal_compatibility():
    context = _context(grant_id="new", expires_at=datetime.now(UTC) + timedelta(minutes=10))
    binding = _build_binding_snapshot(
        uuid4(),
        host_context=context,
        definition_snapshot_digest=None,
        verified_host_grant=_verified(context),
        frozen_manifest_digest="a" * 64,
        connector_profile=profile(),
    )
    assert binding.host_capability.connector_id == "a-real-connector"
    assert binding.host_capability.connector_profile_revision == 3
    assert binding.host_capability.connector_profile_digest == profile().profile_digest
    assert binding.host_capability.manifest_digest == "a" * 64
    with pytest.raises(ValueError, match="exact frozen"):
        _build_binding_snapshot(
            uuid4(),
            host_context=context,
            definition_snapshot_digest=None,
            verified_host_grant=_verified(context),
            connector_profile=profile(),
        )


def test_resolver_refuses_profile_drift_before_private_object_io(monkeypatch):
    context = _context(grant_id="new")
    registry = Mock()
    registry.resolve_binding.return_value = Mock(
        active=True, host_app_id="trench", connector_id="a-real-connector", profile_revision=3
    )
    registry.get_profile.return_value = profile()
    monkeypatch.setattr(
        "agent_storage.postgres.host_connectors.PostgresHostConnectorRegistry",
        lambda *a, **k: registry,
    )
    monkeypatch.setattr(
        "agent_storage.postgres.host_manifest_freeze.load_frozen_manifest", lambda *a, **k: None
    )
    with pytest.raises(HostManifestFreezeError, match="changed after"):
        resolve_admission_profile("unused", "qa", context, "a" * 64)
    registry.resolve_binding.return_value = None
    with pytest.raises(HostManifestFreezeError, match="disappeared"):
        resolve_admission_profile("unused", "qa", context, "a" * 64)
    assert resolve_admission_profile("unused", "qa", context, None) is None
