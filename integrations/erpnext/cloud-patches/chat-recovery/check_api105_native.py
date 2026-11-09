"Pure actual API105 builder contract; captured public profile/wire freeze on stdin, no DB writes."

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.host_connectors import HostConnectorProfileVersion, HostConnectorStatus
from agent_integrations.host_tools import HostToolManifest
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.session_binding import DEFAULT_CAPABILITIES, _build_binding_snapshot
from zebra_agent_api.session_queue import _derive_binding, _resolve_host_connector


def refuses(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("drifted binding accepted")


def main(packet):
    profile = HostConnectorProfileVersion.model_validate(packet["profile"])
    manifest = HostToolManifest.from_payload(packet["frozen_manifest"])
    assert profile.connector_id == "erpnext-native" and profile.profile_revision in (2, 3)
    assert (
        manifest.digest
        == {
            2: "00ed99cb0d692f20553f835f716dda5e69158d04e7230c9455e5b8abbf4fd5d7",
            3: "a78ee2b09eeede8dc54feac65927e56ce155923c491e42ee7bce5ab0a7b7ef76",
        }[profile.profile_revision]
    )
    thread, run = str(uuid4()), str(uuid4())
    context = HostContextEnvelope.model_validate(
        dict(
            grant_id=str(uuid4()),
            host_app_id="erpnext",
            namespace_id="erpnext",
            workspace_ref="erp-u-" + "0" * 40,
            resource_refs=[
                dict(type="thread", id=thread),
                dict(type="principal", id="synthetic-contract-user"),
                dict(type="company", id="synthetic-contract-company"),
                dict(type="run", id=run),
            ],
            scopes=["agent.run", "erpnext.read"],
            limits=dict(max_runtime_seconds=600, max_model_tokens=40000, max_artifact_bytes=1),
            origin="https://erpnext.zebra.local",
            policy_version="erpnext-v1",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    grant = VerifiedHostGrant(
        context=context,
        grant_id=context.grant_id,
        algorithm=JwtAlgorithm.RS256,
        authority_issuer="https://erpnext.zebra.local",
        subject_ref="synthetic-contract-user",
    )
    task_id = str(uuid4())
    kwargs = dict(
        host_context=context,
        definition_snapshot_digest=None,
        deployment_namespace="erpnext",
        frozen_manifest_digest=manifest.digest,
        verified_host_grant=grant,
        resolved_connector_profile=profile,
        frozen_host_manifest=manifest,
        require_resolved_connector=True,
    )
    binding = _build_binding_snapshot(task_id, **kwargs)
    host = binding.host_capability
    assert (host.connector_id, host.connector_profile_revision, host.connector_profile_digest) == (
        profile.connector_id,
        profile.profile_revision,
        profile.profile_digest,
    )
    assert host.manifest_digest == manifest.digest
    # Independently expected resource rules from the captured public schema.
    names = ["erpnext.discover", "erpnext.read"]
    if profile.profile_revision == 3:
        names.append("erpnext.propose")
    assert [tool["name"] for tool in packet["frozen_manifest"]["tools"]] == names
    assert all(not tool.get("resourceBindings") for tool in packet["frozen_manifest"]["tools"])
    canonical = json.dumps(
        [dict(bindings=[], tool=name) for name in names], separators=(",", ":")
    ).encode()
    assert host.resource_binding_digest == hashlib.sha256(canonical).hexdigest() != "0" * 64
    assert (
        binding.effective_capabilities
        == host.capabilities
        == binding.agent_capability_ceiling.capabilities
        == DEFAULT_CAPABILITIES
    )
    assert "erpnext.read" not in binding.effective_capabilities
    derived = _derive_binding(
        task_id,
        definition_snapshot=None,
        **{k: v for k, v in kwargs.items() if k != "definition_snapshot_digest"},
    )
    assert derived.host_capability.connector_profile_digest == profile.profile_digest
    refuses(
        lambda: _build_binding_snapshot(task_id, **{**kwargs, "resolved_connector_profile": None})
    )
    refuses(lambda: _build_binding_snapshot(task_id, **{**kwargs, "frozen_host_manifest": None}))
    refuses(
        lambda: _build_binding_snapshot(task_id, **{**kwargs, "frozen_manifest_digest": "f" * 64})
    )
    refuses(
        lambda: _build_binding_snapshot(
            task_id,
            **{
                **kwargs,
                "resolved_connector_profile": profile.model_copy(
                    update={"status": HostConnectorStatus.REVOKED}
                ),
            },
        )
    )
    refuses(
        lambda: _build_binding_snapshot(
            task_id,
            **{
                **kwargs,
                "resolved_connector_profile": profile.model_copy(
                    update={"workload_identity_ref": "wrong-workload"}
                ),
            },
        )
    )
    # Existing target-validation and internal callers do not acquire new requirements.
    previous = os.environ.pop("ZEBRA_ERPNEXT_CHAT_READONLY", None)
    try:
        assert _resolve_host_connector("unused-no-db", "erpnext", context, manifest.digest) == (
            None,
            None,
        )
    finally:
        if previous is not None:
            os.environ["ZEBRA_ERPNEXT_CHAT_READONLY"] = previous
    prospective = _build_binding_snapshot(
        "prospective-admission",
        host_context=context,
        definition_snapshot_digest=None,
        verified_host_grant=grant,
    )
    assert prospective.host_capability.connector_id == "erpnext-unbound"
    internal = _build_binding_snapshot(task_id, host_context=None, definition_snapshot_digest=None)
    assert internal.host_capability.connector_id == "zebra-internal"
    print(
        json.dumps(
            dict(
                passed=True,
                native_api105_builder=True,
                actual_profile_revision=profile.profile_revision,
                actual_wire_manifest_digest=manifest.digest,
                canonical_resource_rules=True,
                abstract_capabilities_preserved=True,
                rejected_cases=5,
                default_callers_compatible=True,
                database_writes=0,
                model_calls=0,
                actual_new_task_admission="UNVERIFIED",
            )
        )
    )


if __name__ == "__main__":
    try:
        main(json.load(sys.stdin))
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from error
