"""Explicit operator bootstrap of ONLY the empty synthetic E1 namespace."""

import json
import os
from urllib.parse import urlsplit

import httpx
import psycopg
from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.postgres.command_wakeup_discovery import begin_command_backfill
from botocore.exceptions import ClientError
from botocore.session import Session
from zebra_agent_config import load_settings

assert not os.environ.get("ZEBRA_DATABASE_BUDGET_JSON"), "operator uses declared external reserve"
settings = load_settings()
address = urlsplit(settings.database_url)
assert (address.hostname, address.port, address.path) == ("127.0.0.1", 25432, "/ha_e1")
namespace = os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"]
assert namespace == "ha-e1-20261102"
with psycopg.connect(settings.database_url) as connection:
    assert connection.execute("SELECT count(*) FROM session_events").fetchone()[0] == 0
    maximum = connection.execute("SHOW max_connections").fetchone()[0]
    superuser = connection.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
    ).fetchone()[0]
    assert maximum == "256" and superuser is False
    schema = connection.execute("SELECT max(version) FROM zebra_schema_migrations").fetchone()[0]
registry = HostRegistryRecord(
    host_app_id="ha-e1",
    namespace_id=namespace,
    issuer="https://127.0.0.1:28444",
    audience="zebra",
    jwks_uri="https://127.0.0.1:28444/.well-known/jwks.json",
    allowed_origins=("https://ha-e1.invalid",),
    algorithms=("RS256",),
    policy_version="host-v1",
)
store = PostgresHostAuthorityStore(settings.database_url, deployment_namespace=namespace)
existing = store.get_registry(host_app_id="ha-e1", namespace_id=namespace)
assert existing is None or existing == registry, "unexpected existing fixture issuer"
if existing is None:
    store.upsert_registry(registry)
progress = begin_command_backfill(settings.database_url, deployment_namespace=namespace)
assert progress.state == "complete"
client = Session().create_client(
    "s3",
    endpoint_url=os.environ["ZEBRA_S3_ENDPOINT"],
    region_name="us-east-1",
    aws_access_key_id=os.environ["ZEBRA_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["ZEBRA_S3_SECRET_KEY"],
    verify="/e1/ca.crt",
)
bucket = os.environ["ZEBRA_S3_BUCKET"]
assert bucket == "ha-e1-artifacts"
try:
    client.head_bucket(Bucket=bucket)
except ClientError as error:
    if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
        raise
    client.create_bucket(Bucket=bucket)
if client.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
credentials = dict(line.split("=", 1) for line in open("/fixtures/rabbit.env").read().splitlines())
with httpx.Client(
    base_url="http://127.0.0.1:25673/api/",
    trust_env=False,
    auth=("provisioner", credentials["RABBITMQ_ADMIN_PASSWORD"]),
) as admin:
    for role in ("relay", "consumer", "shadow-consumer"):
        for limit, value in (("max-connections", 32), ("max-channels", 64)):
            admin.put(f"user-limits/zebra-{role}/{limit}", json={"value": value}).raise_for_status()
print(
    json.dumps(
        {
            "namespace": namespace,
            "schema": schema,
            "application_superuser": superuser,
            "events_before": 0,
            "cutover": progress.state,
            "s3_versioning": "Enabled",
            "rabbit_runtime_connections_per_user": 32,
        }
    )
)
