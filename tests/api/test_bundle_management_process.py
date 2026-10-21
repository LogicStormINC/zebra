"""Independent HTTP consumer: real API process, scoped config and native receipts."""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.test_bundle_assembly import approved_assembly, settings

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/bundle-validation-v1"
TOKEN = "rtbv_" + "p" * 43
GET = "/management/v1/bundle-contract"
POST = "/management/v1/bundle-validation"
SERVER = """
import sys
import uvicorn
from dataclasses import replace
from tests.test_bundle_assembly import settings
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings
active = replace(settings(), database_url=sys.argv[1],
    api=ApiSettings(auth_token='unrelated-api-token'),
    bundle_management_config=sys.argv[2], runtime_bundle_config=sys.argv[3])
uvicorn.run(create_http_app(settings=active), fd=int(sys.argv[4]),
    log_level='error', access_log=False)
"""


def private_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def row_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with sqlite3.connect(path) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {
            name: connection.execute(
                'SELECT count(*) FROM "' + name.replace('"', '""') + '"'
            ).fetchone()[0]
            for (name,) in tables.fetchall()
        }


def test_real_process_contract_validation_rotation_and_no_execution(tmp_path: Path) -> None:
    from agent_core.domain.runtime_bundle_json import json_digest

    assembly, catalog = approved_assembly(settings())
    bundle = assembly.bundle.model_dump(mode="json")
    scope = {**bundle["manifest"]["scope"], "namespace_id": "local"}
    bundle["manifest"]["scope"] = scope
    bundle["bundle_digest"] = json_digest(bundle["manifest"])
    catalog["scope"] = scope
    approval = {
        "schema_version": "cloud-agent.bundle-management-approval/1",
        "scope": scope,
        "audience": "overdoze",
        "trust_revision": 1,
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expires_at": "2099-01-01T00:00:00Z",
        "actions": ["bundle.contract.read", "bundle.validate"],
    }
    approval_path, catalog_path = tmp_path / "approval.json", tmp_path / "catalog.json"
    private_json(approval_path, approval)
    private_json(catalog_path, catalog)
    database = tmp_path / "sessions.sqlite"
    original_catalog = catalog_path.read_bytes()
    original_bundle = json.dumps(bundle).encode()
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "X-Runtime-Deployment": scope["deployment_id"],
        "X-Runtime-Audience": "overdoze",
        "X-Runtime-Product": scope["product_id"],
        "X-Runtime-Environment": scope["environment"],
        "X-Runtime-Trust-Revision": "1",
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with subprocess.Popen(
            [
                sys.executable,
                "-c",
                SERVER,
                str(database),
                str(approval_path),
                str(catalog_path),
                str(listener.fileno()),
            ],
            cwd=ROOT,
            pass_fds=(listener.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    timeout=2,
                    trust_env=False,
                ) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, process.stderr.read()
                        try:
                            response = client.get(GET, headers=headers)
                            break
                        except httpx.TransportError:
                            assert time.monotonic() < deadline, "owned API did not start"
                            time.sleep(0.05)
                    assert response.status_code == 200, response.text
                    discovered = response.json()
                    assert discovered["contract"] == json.loads(
                        (CONTRACT / "contract.json").read_text()
                    )
                    assert discovered["scope"] == scope
                    counts_before = row_counts(database)
                    post_headers = {
                        **headers,
                        "Content-Type": "application/json",
                        "X-Runtime-Bundle-Contract": discovered["contractDigest"],
                    }
                    valid = client.post(POST, headers=post_headers, content=original_bundle)
                    assert valid.status_code == 200, valid.text
                    receipt = valid.json()
                    assert receipt["bundleDigest"] == bundle["bundle_digest"]
                    assert receipt["assemblyDigest"] == json_digest(
                        {
                            "bundle": bundle,
                            "provider_profile": catalog["providers"][0],
                        }
                    )
                    assert receipt["scope"] == scope and receipt["trustRevision"] == 1
                    assert receipt["contractDigest"] == discovered["contractDigest"]
                    assert receipt["checks"] == {
                        "bundle": "passed",
                        "assetApproval": "passed",
                        "worker": "not_checked",
                        "publication": "not_performed",
                    }
                    assert receipt["approvalDigest"] == json_digest(
                        {key: value for key, value in catalog.items() if key != "baseline_key"}
                    )
                    for prefix in ("rtmg_", "rthm_", "old-api-", "operator-"):
                        denied = client.get(
                            GET, headers={**headers, "Authorization": "Bearer " + prefix + "p" * 43}
                        )
                        assert denied.status_code == 401
                    for changed, status in (
                        ("X-Runtime-Product", 403),
                        ("X-Runtime-Bundle-Contract", 409),
                    ):
                        denied = client.post(
                            POST,
                            headers={**post_headers, changed: "wrong"},
                            content=original_bundle,
                        )
                        assert denied.status_code == status
                    malformed = client.post(
                        POST, headers=post_headers, content=b'{"private":"DO_NOT_ECHO",'
                    )
                    assert malformed.status_code == 422 and "DO_NOT_ECHO" not in malformed.text
                    scoped = json.loads(original_bundle)
                    scoped["manifest"]["scope"]["target_id"] = "other-target"
                    scoped["bundle_digest"] = json_digest(scoped["manifest"])
                    assert client.post(POST, headers=post_headers, json=scoped).status_code == 403
                    for vector in json.loads((CONTRACT / "negative-vectors.json").read_text()):
                        rejected = client.post(POST, headers=post_headers, content=vector["raw"])
                        assert rejected.status_code == vector["status"], vector["name"]
                    private_json(approval_path, {**approval, "actions": ["bundle.contract.read"]})
                    assert client.get(GET, headers=headers).status_code == 200
                    assert (
                        client.post(POST, headers=post_headers, content=original_bundle).status_code
                        == 403
                    )
                    private_json(approval_path, {**approval, "credential_sha256": "0" * 64})
                    assert client.get(GET, headers=headers).status_code == 401
                    assert row_counts(database) == counts_before
                    assert catalog_path.read_bytes() == original_catalog
                    assert json.dumps(bundle).encode() == original_bundle
                    for text in (valid.text, malformed.text, discovered.__repr__()):
                        assert TOKEN not in text and "baseline_key" not in text
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
