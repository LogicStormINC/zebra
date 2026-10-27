"""Canonical public facts and exact mounted/binding lifecycle, without a BFF emulator."""

from copy import deepcopy
from datetime import UTC, datetime

from agent_core.domain.client_capabilities import canonical_client_capability_digest

from tests.api.test_client_runtime_api import _handle
from tests.api.test_client_surface import surface


def test_native_metadata_uses_exact_allowed_profile_contracts():
    api, bundle, _, headers, body, path = surface()
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code == 201, response.body
    result = response.body
    profile = bundle.frontend_capabilities.get_profile(body["mount"]["frontend_app_id"], 1)
    expected = {
        name: canonical_client_capability_digest(
            profile.action_contract(name).model_dump(mode="json")
        )
        for name in result["allowed_actions"]
    }
    assert result["action_contract_digests"] == expected
    assert result["client_surface_metadata_contract_version"] == 1
    assert result["binding_mounted_snapshot_digest"] == result["mounted_snapshot_digest"]
    assert result["profile_digest"] == profile.profile_digest
    caps = _handle(api, "GET", "/capabilities/runtime")
    assert caps.body["client_surface_metadata_contract_version"] == 1


def test_same_action_names_new_ui_revision_updates_binding_snapshot_and_fence():
    api, bundle, session, headers, body, path = surface()
    first = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == 201
    newer = deepcopy(body)
    newer["mount"]["ui_revision"] = 2
    newer["mount"]["mounted_at"] = datetime.now(UTC).isoformat()
    second = _handle(api, "POST", path, body=newer, headers=headers)
    assert second.status_code == 201, second.body
    assert second.body["binding_id"] == first.body["binding_id"]
    assert second.body["binding_revision"] == first.body["binding_revision"] + 1
    assert second.body["binding_digest"] != first.body["binding_digest"]
    assert second.body["controller_fence_token"] != first.body["controller_fence_token"]
    assert (
        second.body["binding_mounted_snapshot_digest"]
        == bundle.client_sessions.snapshots[session].snapshot_digest
    )
    replay = _handle(api, "POST", path, body=newer, headers=headers)
    assert replay.status_code == 201
    assert replay.body["binding_revision"] == second.body["binding_revision"]
    assert replay.body["binding_digest"] == second.body["binding_digest"]
    for token, status in [
        (first.body["controller_fence_token"], 409),
        (replay.body["controller_fence_token"], 200),
    ]:
        heartbeat = _handle(
            api,
            "POST",
            f"/v1/client-sessions/{session}/heartbeat",
            headers={**headers, "X-Zebra-Client-Fence": token},
            body={
                "task_id": path.split("/")[3],
                "run_id": "fixture-run",
                "run_binding_id": replay.body["binding_id"],
            },
        )
        assert heartbeat.status_code == status


def test_narrowed_observer_metadata_has_no_action_digest_or_new_fence():
    api, _, _, headers, body, path = surface()
    body["controller"] = False
    first = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == 201
    body["mount"]["mounted_actions"] = []
    body["mount"]["ui_revision"] = 2
    result = _handle(api, "POST", path, body=body, headers=headers)
    assert result.status_code == 201, result.body
    assert result.body["allowed_actions"] == []
    assert result.body["action_contract_digests"] == {}
    assert result.body["controller_fence_token"] is None
    assert result.body["binding_mounted_snapshot_digest"] == result.body["mounted_snapshot_digest"]


def test_mount_changed_during_binding_never_returns_mixed_success():
    api, bundle, session, headers, body, path = surface()
    original = bundle.client_sessions.save_run_binding

    def concurrent_mount(binding):
        original(binding)
        old = bundle.client_sessions.snapshots[session]
        bundle.client_sessions.snapshots[session] = old.model_copy(
            update={"ui_revision": old.ui_revision + 1}
        )

    bundle.client_sessions.save_run_binding = concurrent_mount
    result = _handle(api, "POST", path, body=body, headers=headers)
    assert result.status_code == 409
    assert "controller_fence_token" not in result.body


def test_narrowed_mount_cannot_widen_and_split_binding_returns_same_public_facts():
    api, _, _, headers, body, path = surface()
    original = deepcopy(body)
    body["mount"]["mounted_actions"] = []
    first = _handle(api, "POST", path, body=body, headers=headers)
    assert first.status_code == 201
    original["mount"]["ui_revision"] = 2
    rejected = _handle(api, "POST", path, body=original, headers=headers)
    assert rejected.status_code == 409
    split = _handle(
        api,
        "POST",
        path.replace("client-surface", "client-bindings"),
        headers=headers,
        body={k: v for k, v in body.items() if k != "mount"},
    )
    assert split.status_code == 201
    for key in (
        "binding_id",
        "binding_digest",
        "mounted_snapshot_digest",
        "ui_revision",
        "binding_mounted_snapshot_digest",
        "action_contract_digests",
    ):
        assert split.body[key] == first.body[key]


def test_disabled_client_plane_does_not_advertise_metadata_support():
    from tests.api.test_client_runtime_api import _api

    result = _handle(_api(None), "GET", "/capabilities/runtime")
    assert result.body["client_surface_metadata_contract_version"] == 0


def test_competing_fence_rotation_cannot_return_stale_success():
    api, bundle, _, headers, body, path = surface()
    original = bundle.client_control_leases.get_active

    def rotated(binding_id):
        lease = original(binding_id)
        return lease.model_copy(update={"fence_hash": "0" * 64})

    bundle.client_control_leases.get_active = rotated
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code == 409
    assert "controller_fence_token" not in response.body


def test_mount_changed_before_binding_cannot_acknowledge_a_different_request():
    api, bundle, session, headers, body, path = surface()
    original = bundle.client_sessions.save_mounted_snapshot

    def newer_mount(snapshot):
        original(snapshot)
        bundle.client_sessions.snapshots[session] = snapshot.model_copy(
            update={"ui_revision": snapshot.ui_revision + 1}
        )

    bundle.client_sessions.save_mounted_snapshot = newer_mount
    response = _handle(api, "POST", path, body=body, headers=headers)
    assert response.status_code == 409
    assert "controller_fence_token" not in response.body
