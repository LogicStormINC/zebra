"""Host connector profile/binding contract tests."""

from __future__ import annotations

import pytest
from agent_core.domain.host_connectors import (
    HostConnectorBinding,
    HostConnectorProfileVersion,
    HostConnectorStatus,
    accepts_new_tasks,
    fails_closed_for_running_tasks,
)
from pydantic import ValidationError


def _profile(**overrides: object) -> HostConnectorProfileVersion:
    payload: dict[str, object] = {
        "host_app_id": "trench",
        "connector_id": "trench-main",
        "profile_revision": 1,
        "base_uri": "https://trench.example.com",
        "manifest_path": "/manifest",
        "invoke_path_template": "/tools/invoke",
        "reconcile_path_template": "/tools/reconcile",
        "supported_protocol_versions": ("host-capability-protocol/1",),
        "workload_identity_ref": "workload/zebra-worker",
        "credential_ref": "credentials/trench-hmac",
    }
    payload.update(overrides)
    return HostConnectorProfileVersion(**payload)  # type: ignore[arg-type]


class TestHostConnectorProfileVersion:
    def test_valid_profile_has_canonical_digest(self) -> None:
        profile = _profile()
        assert len(profile.profile_digest) == 64
        assert profile.profile_digest == _profile().profile_digest

    def test_revision_change_changes_digest(self) -> None:
        assert _profile().profile_digest != _profile(profile_revision=2).profile_digest

    def test_base_uri_must_be_bare_https(self) -> None:
        for bad in ("http://trench.example.com", "https://host/query?x=1", "trench.example.com"):
            with pytest.raises(ValidationError):
                _profile(base_uri=bad)

    def test_paths_must_be_rooted_and_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _profile(manifest_path="manifest")
        with pytest.raises(ValidationError):
            _profile(invoke_path_template="/tools/$tool")

    def test_credential_refs_reject_secret_material(self) -> None:
        with pytest.raises(ValidationError):
            _profile(credential_ref="secret/hmac-key")

    def test_duplicate_protocol_versions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _profile(supported_protocol_versions=("v1", "v1"))


class TestLifecycle:
    def test_published_accepts_new_tasks_deprecated_does_not(self) -> None:
        assert accepts_new_tasks(HostConnectorStatus.PUBLISHED)
        assert not accepts_new_tasks(HostConnectorStatus.DEPRECATED)
        assert not accepts_new_tasks(HostConnectorStatus.REVOKED)

    def test_revoked_fails_closed_for_running_tasks(self) -> None:
        assert fails_closed_for_running_tasks(HostConnectorStatus.REVOKED)
        assert not fails_closed_for_running_tasks(HostConnectorStatus.DEPRECATED)


class TestHostConnectorBinding:
    def test_binding_pins_namespace_to_revision(self) -> None:
        binding = HostConnectorBinding(
            host_app_id="trench",
            namespace_id="tenant-a",
            connector_id="trench-main",
            profile_revision=3,
            binding_revision=1,
        )
        assert binding.active is True
        assert binding.profile_revision == 3
