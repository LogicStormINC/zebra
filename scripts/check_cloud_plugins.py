"""Offline native Cloud Plugin proof. Only --config names a private task infra file."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from uuid import uuid4

import psycopg
from agent_storage import apply_postgres_migrations, bootstrap_control_plane_epoch
from psycopg import sql

from tests.cloud_plugins.native_fixture import (
    NativeFixture,
    admit,
    bundle,
    components,
    manage,
    private_config,
    seed_task,
)
from tests.cloud_plugins.native_metrics import measured
from tests.cloud_plugins.native_process import refused
from tests.cloud_plugins.native_worker import recover
from tests.worker.test_plugin_child_authority import assert_child_authority


def run(config_path: Path) -> dict:
    config = private_config(config_path)
    expected = {"zebra-cloud-plugin-check-20261019", "zebra-cloud-plugin-objects-20261019"}
    assert set(config["owned_containers"]) == expected
    for name in sorted(expected):
        checked = subprocess.run(
            ["docker", "inspect", "--format", '{{ index .Config.Labels "zebra.task" }}', name],
            capture_output=True,
            text=True,
            check=True,
        )
        assert checked.stdout.strip() == "cloud-plugin", "container ownership mismatch"
    schema = "cloud_plugin_accept_" + uuid4().hex
    fixture = NativeFixture(config, schema)
    rows, arms = [], []
    with psycopg.connect(config["postgres_dsn"]) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        apply_postgres_migrations(fixture.dsn)
        bootstrap_control_plane_epoch(fixture.dsn, deployment_namespace=fixture.namespace)
        counter_rows = []
        with measured(counter_rows, arm="counter", phase="two_real_opens", temperature="cold"):
            with psycopg.connect(fixture.dsn) as connection:
                assert connection.execute("SELECT 1").fetchone() == (1,)
            with fixture.io.connect() as connection:
                assert connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        assert counter_rows[0]["physical_connects"] == 2
        assert counter_rows[0]["attempted_driver_sql"] == 2
        with tempfile.TemporaryDirectory(
            prefix="cloud-plugin-accept-", dir=config_path.parent
        ) as temporary:
            root = Path(temporary).resolve()
            bundle_root = root / "trusted"
            bundle_root.mkdir()
            digest = bundle(bundle_root)
            skill, mcp = asyncio.run(components(fixture))
            service, admission = fixture.compose(bundle_root, digest)
            payload = {
                "package_digest": digest,
                "bindings": [
                    {
                        "component_id": "proof-skill",
                        "kind": "skill-bundle",
                        "installation_id": skill.installation_id,
                    },
                    {
                        "component_id": "proof-mcp",
                        "kind": "mcp-http",
                        "connection_id": mcp.connection_id,
                    },
                ],
            }
            created, record = asyncio.run(manage(service, method="POST", payload=payload))
            assert created == 201 and record["enabled"] is False
            plugin_id = record["installation_id"]
            status, record = asyncio.run(
                manage(
                    service,
                    method="PATCH",
                    identifier=plugin_id,
                    revision=1,
                    payload={"enabled": True},
                )
            )
            assert status == 200 and record["revision"] == 2
            selection = {"plugins": [{"installation_id": plugin_id, "revision": 2}]}
            for pair, ordered in enumerate((("legacy", "plugin"), ("plugin", "legacy"))):
                for arm in ordered:
                    key = f"{arm}-{pair}"
                    task = seed_task(fixture, skill.version.skill_id, root)
                    with measured(
                        rows,
                        arm=key,
                        phase="admission",
                        temperature="first-pair" if pair == 0 else "warm-second-pair",
                    ):
                        accepted = admit(
                            fixture, admission, task, selection if arm == "plugin" else None
                        )
                    assert accepted.payload["extension_snapshot_digest"]
                    arms.append({"name": key, "session_id": str(task)})
            plugin_task = next(a["session_id"] for a in arms if a["name"] == "plugin-0")
            from uuid import UUID

            from agent_core.domain.identifiers import SessionId

            child_proofs = [
                assert_child_authority(
                    fixture, SessionId(UUID(plugin_task)), root, search_allowed=False
                )
            ]
            parent = seed_task(fixture, skill.version.skill_id, root, network="full-gateway")
            admit(fixture, admission, parent, selection)
            child_proofs.append(assert_child_authority(fixture, parent, root, search_allowed=True))
            # Separate negative installation preserves the positive accepted snapshot.
            status, negative = asyncio.run(
                manage(service, method="POST", payload=payload, key="negative-install")
            )
            assert status == 201
            negative_id = negative["installation_id"]
            assert (
                asyncio.run(
                    manage(
                        service,
                        method="PATCH",
                        identifier=negative_id,
                        revision=1,
                        payload={"enabled": True},
                    )
                )[0]
                == 200
            )
            negative_task = seed_task(fixture, skill.version.skill_id, root)
            admit(
                fixture,
                admission,
                negative_task,
                {"plugins": [{"installation_id": negative_id, "revision": 2}]},
            )
            assert (
                asyncio.run(
                    manage(
                        service,
                        method="PATCH",
                        identifier=negative_id,
                        revision=2,
                        payload={"enabled": False},
                    )
                )[0]
                == 200
            )
            assert refused(fixture, negative_task, root)
            assert (
                asyncio.run(
                    manage(
                        service, method="PATCH", identifier=negative_id, revision=3, payload=payload
                    )
                )[0]
                == 200
            )
            assert (
                asyncio.run(
                    manage(
                        service,
                        method="PATCH",
                        identifier=negative_id,
                        revision=4,
                        payload={"enabled": True},
                    )
                )[0]
                == 200
            )
            assert refused(fixture, negative_task, root)
            status, public = asyncio.run(manage(service, method="GET", identifier=plugin_id))
            assert status == 200 and "receipt" not in public
            extension = recover(fixture, SessionId(UUID(plugin_task)))
            pinned = asyncio.run(
                service.store.get_revision(
                    scope=extension.scope, installation_id=plugin_id, revision=2
                )
            )
            assert pinned.package.receipt.object_version not in {"", "null"}
            manifest = {
                "package_digest": pinned.package.package_digest,
                "manifest_digest": pinned.package.manifest_digest,
                "object_sha256": pinned.package.expectation.sha256,
                "object_bytes": pinned.package.expectation.size_bytes,
                "versioned_receipt": True,
                "skill_files": len(pinned.package.skill_files("proof-skill")),
            }
            # Remove ALL trusted input bytes before the independent interpreter starts.
            shutil.rmtree(bundle_root)
            state_path = root / "coordinates.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema": schema,
                        "bundle_root": str(bundle_root),
                        "arms": arms,
                        "plugin_task": plugin_task,
                        "rebound_task": str(negative_task),
                    }
                )
            )
            state_path.chmod(0o600)
            child = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tests.cloud_plugins.native_process",
                    "--config",
                    str(config_path.resolve()),
                    "--state",
                    str(state_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            native = json.loads(child.stdout)
            assert child.returncode == 0, native
            assert native["pid"] != os.getpid()
            return {
                "status": "passed",
                "counter_selfcheck": counter_rows[0],
                "native_postgres": True,
                "native_versioned_minio": True,
                "independent_process": True,
                "local_bundle_removed": True,
                "package": manifest,
                "rows": rows + native["rows"],
                "workloads": native["proofs"],
                "child_isolation": child_proofs,
                "negatives": ["disabled", *native["negatives"]],
                "independent_legacy_source_survives": native["independent_legacy_source_survives"],
                "boundaries": [
                    "VerifiedHostGrant claim fixture; "
                    "JWT HTTP signature verification outside this check",
                    "MCP urllib HTTPS opener and DNS-public check stubbed; "
                    "no real MCP HTTPS or server",
                    "No model/provider/search/upstream calls; "
                    "actual harness tool batches and durable HITL",
                    "Fixed 4-tool workloads; attempted driver SQL "
                    "excludes server trigger statements",
                    "Admission/recovery/tool timings include harness evidence persistence; "
                    "no TTFT/P95 claim",
                    "Cold means first measured operation in that interpreter; "
                    "warm means later operation",
                    "No per-delta path, service activation, Trench/Desktop "
                    "or production acceptance",
                ],
            }
    finally:
        fixture.client.close()
        with psycopg.connect(config["postgres_dsn"]) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path, help="mode-600 task-owned infrastructure JSON"
    )
    args = parser.parse_args()
    try:
        report = run(args.config.resolve())
    except Exception as exc:
        # Never print exception messages, locals, DSNs, response bodies or credentials.
        report = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "frames": [
                {"file": Path(f.filename).name, "line": f.lineno}
                for f in traceback.extract_tb(exc.__traceback__)
            ],
        }
    output = args.config.resolve().parent / "native-evidence.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
