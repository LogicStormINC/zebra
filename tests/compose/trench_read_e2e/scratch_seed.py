"""Explicit scratch preparation. Observation paths never perform this maintenance."""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path
from typing import Any

from scratch_topology import inspect_owned, private_json
from support import E2EError, request, require_status


def host_dsn(environment: dict[str, str], suffix: str) -> str:
    return (
        f"postgresql://qa:{environment['PG_SECRET']}@127.0.0.1:{environment['PG_PORT']}/"
        f"{environment['SCRATCH_SCOPE']}_{suffix}"
    )


def seed_storage(environment: dict[str, str]) -> None:
    import psycopg
    from psycopg import sql

    scope = environment["SCRATCH_SCOPE"]
    inspect_owned(environment, [scope + "-postgres", scope + "-object_store"])
    deadline = time.monotonic() + 60
    while True:
        try:
            with psycopg.connect(
                host_dsn(environment, "zebra"), connect_timeout=2, autocommit=True
            ) as connection:
                # The identifier is generated locally; no arbitrary database target is accepted.
                existing = connection.execute(
                    "SELECT datname FROM pg_database WHERE datname=%s", (scope + "_trench",)
                ).fetchone()
                if existing is None:
                    connection.execute(
                        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scope + "_trench"))
                    )
            break
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                raise E2EError("scratch_postgres_not_ready") from None
            time.sleep(0.2)
    seed_object_bucket(environment)


def seed_object_bucket(environment: dict[str, str]) -> None:
    """Prepare only the proved scratch bucket; never rewrite existing objects."""
    from botocore.session import Session  # type: ignore[import-untyped]

    scope = environment["SCRATCH_SCOPE"]
    if re.fullmatch(r"zebra-progress-e2e-qa-[0-9a-f]{12}", scope) is None:
        raise E2EError("scratch_target_not_owned")
    row = inspect_owned(environment, [scope + "-object_store"])[0]
    if row["NetworkSettings"]["Ports"].get("9000/tcp") != [
        {"HostIp": "127.0.0.1", "HostPort": environment["MINIO_PORT"]}
    ]:
        raise E2EError("scratch_object_endpoint_not_owned")
    client = Session().create_client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{environment['MINIO_PORT']}",
        aws_access_key_id=environment["MINIO_USER"],
        aws_secret_access_key=environment["MINIO_SECRET"],
        region_name="us-east-1",
    )
    try:
        if not any(bucket["Name"] == scope for bucket in client.list_buckets()["Buckets"]):
            client.create_bucket(Bucket=scope)
        if client.get_bucket_versioning(Bucket=scope).get("Status") != "Enabled":
            client.put_bucket_versioning(
                Bucket=scope, VersioningConfiguration={"Status": "Enabled"}
            )
            if client.get_bucket_versioning(Bucket=scope).get("Status") != "Enabled":
                raise E2EError("scratch_bucket_versioning_not_enabled")
    except Exception:
        raise E2EError("scratch_minio_seed_failed") from None
    finally:
        client.close()


def seed_authority(environment: dict[str, str]) -> None:
    from agent_storage.postgres.host_auth import HostRegistryRecord, PostgresHostAuthorityStore

    scope = environment["SCRATCH_SCOPE"]
    inspect_owned(environment, [scope + "-postgres"])
    PostgresHostAuthorityStore(
        host_dsn(environment, "zebra"), deployment_namespace=scope
    ).upsert_registry(
        HostRegistryRecord(
            host_app_id="trench",
            namespace_id=scope,
            issuer=environment["BROKER_ORIGIN"],
            audience="zebra",
            jwks_uri=f"https://{scope}-proxy:8444/.well-known/jwks.json",
            allowed_origins=(environment["HOST_ORIGIN"],),
            algorithms=("RS256",),
            policy_version="trench-native-v15",
            active=True,
        )
    )


def seed_identity(root: Path, environment: dict[str, str]) -> dict[str, Any]:
    scope = environment["SCRATCH_SCOPE"]
    inspect_owned(environment, [scope + "-proxy", scope + "-trench_api", scope + "-postgres"])
    response = request(
        "POST",
        environment["HOST_ORIGIN"] + "/api/trench-ai/auth/register",
        payload={
            "email": secrets.token_hex(8) + "@scratch.invalid",
            "password": secrets.token_urlsafe(32),
            "display_name": "Isolated QA",
        },
        timeout=10,
    )
    require_status(response, {201})
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise E2EError("scratch_identity_invalid")
    data = body["data"]
    viewer = data["viewer"]
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    values = {
        "TRENCH_E2E_BFF_URL": environment["HOST_ORIGIN"],
        "TRENCH_E2E_READ_TOOLS_URL": environment["HOST_ORIGIN"] + "/api/trench-ai/agent",
        "TRENCH_E2E_SESSION_COOKIE": cookie,
        "TRENCH_E2E_USER_ID": viewer["user_id"],
        "TRENCH_E2E_WORKSPACE_ID": viewer["workspace_id"],
        "TRENCH_E2E_RUNTIME_TASKS_URL": f"https://{scope}-proxy:8445/tasks",
        "TRENCH_E2E_HEALTH_URL": environment["HOST_ORIGIN"] + "/api/health/ready",
        "TRENCH_E2E_DATABASE_DSN": host_dsn(environment, "trench"),
        "TRENCH_E2E_REDIS_URL": f"redis://127.0.0.1:{environment['REDIS_PORT']}/0",
        "ZEBRA_E2E_REDIS_URL": f"redis://127.0.0.1:{environment['REDIS_PORT']}/1",
        "ZEBRA_E2E_BASE_URL": f"https://127.0.0.1:{environment['ZEBRA_TLS_PORT']}",
        "ZEBRA_E2E_HEALTH_URL": f"https://127.0.0.1:{environment['ZEBRA_TLS_PORT']}/health",
        "ZEBRA_E2E_DATABASE_DSN": host_dsn(environment, "zebra"),
        "ZEBRA_E2E_GRANT_EXCHANGE_URL": environment["BROKER_ORIGIN"] + "/exchange",
        "ZEBRA_E2E_ISOLATION_MANIFEST": str(root / "isolation.json"),
        "ZEBRA_E2E_TIMEOUT_SECONDS": "120",
    }
    for prefix in ("ZEBRA", "TRENCH"):
        values[prefix + "_E2E_OBJECT_STORE_HEALTH_URL"] = (
            f"http://127.0.0.1:{environment['MINIO_PORT']}/minio/health/live"
        )
    private_json(root / "runner-inputs.json", values)
    return values
