"""Fresh-process recovery reads only durable stores; state contains coordinates only."""

import argparse
import asyncio
import json
import os
import traceback
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.ports.extensions import ExtensionNotFoundError
from agent_integrations.plugins.publication import PluginPackagePublicationService
from zebra_agent_worker.worker_plugins import WorkerPluginSource, prepare_worker_plugins

from tests.cloud_plugins.native_fixture import NativeFixture, private_config
from tests.cloud_plugins.native_metrics import measured
from tests.cloud_plugins.native_worker import catalogs, recover, workload


def refused(fixture, session_id, root):
    extension = recover(fixture, session_id)
    try:
        prepare_worker_plugins(
            extension,
            source=WorkerPluginSource(
                fixture.plugins,
                PluginPackagePublicationService(root, (), fixture.objects, fixture.namespace),
            ),
            skills_available=True,
            mcp_available=True,
        )
    except PluginAuthorityUnavailable:
        return True
    raise AssertionError("unavailable source was not typed-stopped")


def run(config_path: Path, state_path: Path):
    state = private_config_state(state_path)
    fixture = NativeFixture(private_config(config_path), state["schema"])
    root = state_path.parent / "fresh-worker"
    root.mkdir()
    assert not Path(state["bundle_root"]).exists()
    rows, proofs = [], []
    for index, arm in enumerate(state["arms"]):
        session_id = SessionId(UUID(arm["session_id"]))
        temperature = "cold-process-first-arm" if index == 0 else "warm-process-later-arm"
        with measured(
            rows, arm=arm["name"], phase="recovery_and_catalogs", temperature=temperature
        ):
            extension = recover(fixture, session_id)
            assert extension is not None
            prepared = catalogs(fixture, extension, session_id, root)
        with measured(
            rows, arm=arm["name"], phase="native_tools_and_durable_HITL", temperature=temperature
        ):
            proofs.append(workload(fixture, extension, session_id, root, prepared))
    plugin_id = SessionId(UUID(state["plugin_task"]))
    extension = recover(fixture, plugin_id)
    # Worker feature-off is typed refusal, including after process restart.
    try:
        recover(fixture, plugin_id, allow_plugins=False)
    except PluginAuthorityUnavailable:
        pass
    else:
        raise AssertionError("feature-off accepted a Plugin Turn")
    pin = extension.snapshot.plugins[0]
    record = asyncio.run(
        fixture.plugins.get_revision(
            scope=extension.scope,
            installation_id=pin.installation_id,
            revision=pin.revision,
        )
    )
    changed_scope = extension.scope.model_copy(update={"principal_id": "other"})
    try:
        asyncio.run(fixture.plugins.get(scope=changed_scope, installation_id=pin.installation_id))
    except ExtensionNotFoundError:
        pass
    else:
        raise AssertionError("scope leaked")
    assert refused(fixture, SessionId(UUID(state["rebound_task"])), root)
    # A new latest version MUST NOT replace the immutable accepted version.
    key = fixture.objects._key(record.package.expectation)
    latest = fixture.client.put_object(
        Bucket=fixture.config["s3_bucket"],
        Key=key,
        Body=b"UNAPPROVED LATEST",
    )["VersionId"]
    assert latest != record.package.receipt.object_version
    assert not refused_if_valid(fixture, plugin_id, root)
    fixture.client.delete_object(
        Bucket=fixture.config["s3_bucket"],
        Key=key,
        VersionId=record.package.receipt.object_version,
    )
    assert refused(fixture, plugin_id, root)
    # Independently admitted legacy origin still reads/executes the same components.
    direct_id = SessionId(UUID(state["arms"][0]["session_id"]))
    direct = recover(fixture, direct_id)
    assert not direct.snapshot.plugins
    skill, mcp, leases, lease = catalogs(fixture, direct, direct_id, root)
    try:
        assert (
            "NATIVE-SKILL-PROOF"
            in skill.read("native-proof", file_path="references/support.txt").content
        )
        assert mcp.model_tools
    finally:
        leases.release(direct_id, fence=lease.fence)
    assert not any(
        e.event_type.value == "model_request_started"
        for e in fixture.events.list_for_session(plugin_id)
    )
    return {
        "pid": os.getpid(),
        "rows": rows,
        "proofs": proofs,
        "negatives": [
            "scope",
            "feature-off",
            "rebind",
            "missing-pinned-version-no-latest-fallback",
        ],
        "independent_legacy_source_survives": True,
    }


def refused_if_valid(fixture, session_id, root):
    extension = recover(fixture, session_id)
    guard = prepare_worker_plugins(
        extension,
        source=WorkerPluginSource(
            fixture.plugins,
            PluginPackagePublicationService(root, (), fixture.objects, fixture.namespace),
        ),
        skills_available=True,
        mcp_available=True,
    )
    guard.validate()
    return False


def private_config_state(path):
    assert path.stat().st_mode & 0o777 == 0o600
    return json.loads(path.read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.config, args.state)))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "failed": type(exc).__name__,
                    "frames": [
                        {"file": Path(f.filename).name, "line": f.lineno}
                        for f in traceback.extract_tb(exc.__traceback__)
                    ],
                }
            )
        )
        raise SystemExit(1) from None
