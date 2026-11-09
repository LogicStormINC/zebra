"""Actual loopback HTTP/JWT reads over the migrated clone; no execution.

The QA public-key resolver is injected at the documented crypto port. Production
signing keys/trust and business data are never used or changed. S3 is not tested.
"""

import json
import os
import socket
import time
from dataclasses import replace
from datetime import UTC as UTC
from datetime import datetime as datetime
from pathlib import Path
from threading import Thread
from uuid import uuid4

import httpx
import jwt
import psycopg
import uvicorn
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.identifiers import TaskId
from agent_security.jwt_adapter import PyJwtHostGrantDecoder
from agent_storage import CloudCompositionSettings, PostgresHostAuthorityStore
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.direct_control import PostgresDirectControl
from botocore.config import Config
from botocore.session import Session
from check_capability_upgrade import read_inventory, require_isolated
from cryptography.hazmat.primitives.asymmetric import rsa
from zebra_agent_api import create_http_app
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_config import load_settings


class QaPublicKey:
    def __init__(self, key, uri):
        self.key, self.uri = key, uri

    def resolve(self, jwks_uri, token, *, deadline=None):
        if jwks_uri != self.uri or jwt.get_unverified_header(token).get("kid") != "isolated-qa":
            raise ValueError("QA signing key does not match this configured authority")
        return self.key.public_key()


def main():
    dsn = os.environ["ERP_CAPABILITY_QA_DSN"]
    require_isolated(dsn)
    output = Path(os.environ["ERP_CAPABILITY_QA_OUTPUT"])
    if output.exists():
        raise ValueError("Retain earlier HTTP evidence")
    definitions, before = read_inventory(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        identity = connection.execute(
            "SELECT task_id FROM agent_tasks "
            "WHERE deployment_namespace='erpnext' ORDER BY task_id LIMIT 1"
        ).fetchone()[0]
    binding = PostgresDirectControl(dsn, deployment_namespace="erpnext").load_task_binding(
        TaskId(identity)
    )
    assert binding is not None
    context = binding.host_capability.host_context
    assert context is not None
    issuer = binding.host_capability.authority_issuer
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace="erpnext")
    record = next(r for r in registry.list_registries() if r.issuer == issuer)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry, PyJwtHostGrantDecoder(QaPublicKey(key, record.jwks_uri))
    )
    # Real S3 adapter, with no production credentials or reachable object endpoint.
    # No content/download route is invoked; metadata-only acceptance cannot prove S3.
    client = Session().create_client(
        "s3",
        endpoint_url="http://127.0.0.1:9",
        aws_access_key_id="isolated-qa",
        aws_secret_access_key="isolated-qa",
        region_name="us-east-1",
        config=Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 0}),
    )
    scope = OpaqueAuthorityScope(authority_issuer=issuer, namespace_id=context.namespace_id)
    composition = CloudCompositionSettings(
        dsn,
        "erpnext",
        os.urandom(32),
        S3ArtifactObjectStore(client, bucket="isolated-qa"),
        scope,
        scope,
    )
    settings = load_settings(
        {
            "ZEBRA_PROFILE": "cloud",
            "ZEBRA_DATABASE_URL": dsn,
            "ZEBRA_STORAGE_AUTHORITY": "postgresql",
            "ZEBRA_DEPLOYMENT": "cloud",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
            "ZEBRA_RUNTIME_IMAGE": os.environ["ERP_CAPABILITY_QA_RUNTIME_IMAGE"],
        }
    )
    settings = replace(settings, cloud_extensions_read_enabled=True)
    application = create_http_app(
        settings=settings, cloud_composition=composition, host_grant_authorizer=authorizer
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="error", access_log=False))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    outcomes = []
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as http:

            def request(path, *, alterations=None, scopes=None, signed=True):
                now = int(time.time())
                refs = [r.model_dump(mode="json", by_alias=True) for r in context.resource_refs]
                principal = next(
                    r.resource_id for r in context.resource_refs if r.resource_type == "principal"
                )
                claims = {
                    "iss": issuer,
                    "aud": record.audience,
                    "sub": principal,
                    "jti": str(uuid4()),
                    "iat": now,
                    "nbf": now,
                    "exp": now + 300,
                    "host_app_id": context.host_app_id,
                    "namespace_id": context.namespace_id,
                    "workspace_ref": context.workspace_ref,
                    "resource_refs": refs,
                    "scopes": scopes or list(context.scopes),
                    "origin": context.origin,
                    "policy_version": context.policy_version,
                    "limits": context.limits.model_dump(mode="json"),
                }
                claims.update(alterations or {})
                token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "isolated-qa"})
                headers = {"Origin": context.origin}
                if signed:
                    headers["Authorization"] = "Bearer " + token
                response = http.get(path, headers=headers)
                outcomes.append(
                    {
                        "path": path,
                        "status": response.status_code,
                        "case": sorted((alterations or {}).keys())
                        or ("signed" if signed else "unsigned"),
                    }
                )
                with output.with_suffix(".requests.jsonl").open("a") as log:
                    log.write(json.dumps(outcomes[-1]) + "\n")
                return response

            path = f"/tasks/{identity}/header"
            response = request(path)
            assert response.status_code == 200, (response.status_code, response.text[:300])
            assert response.json()["task_id"] == str(identity)
            assert request(path, signed=False).status_code == 401
            assert request(
                path, alterations={"workspace_ref": "foreign-workspace"}
            ).status_code in {403, 404}
            assert request(path, alterations={"exp": int(time.time()) - 1}).status_code in {
                401,
                403,
            }
            for suffix in ["usage", "artifacts"]:
                response = request(
                    f"/tasks/{identity}/{suffix}", scopes=["agent.run", "artifact.read"]
                )
                assert response.status_code == 200, (
                    suffix,
                    response.status_code,
                    response.text[:300],
                )
            for path in ["/v1/extensions/skill-installations", "/v1/extensions/mcp-connections"]:
                response = request(path, scopes=["agent.run", "extensions.read"])
                assert response.status_code == 200, (
                    path,
                    response.status_code,
                    response.text[:300],
                )
                assert request(path, scopes=["agent.run"]).status_code == 403
            response = request("/schedules", scopes=["agent.run", "schedule.read"])
            assert response.status_code == 200, (response.status_code, response.text[:300])
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        client.close()
    _, after = read_inventory(dsn, definitions)
    changed = [table for table in before if before[table] != after[table]]
    assert set(changed) <= {"host_grant_replay_ledger", "host_grant_audit"}, changed
    # Signed HTTP requests consume jti/audit facts in this isolated DB, never in production.
    result = {
        "stage": "signed_http_reads",
        "outcomes": outcomes,
        "changed_clone_tables": changed,
        "ephemeral_qa_signing_key": True,
        "production_keys_used": False,
        "model_calls": 0,
        "search_calls": 0,
        "worker_started": False,
        "s3_payload_tested": False,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    output.chmod(0o600)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
