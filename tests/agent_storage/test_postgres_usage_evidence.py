import json
from datetime import UTC, datetime

from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_storage.postgres.usage_evidence import PostgresUsageEvidenceStore


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return self

    def fetchall(self):
        return []


class _Database:
    deployment_namespace = "cloud"

    def __init__(self):
        self.connection = _Connection()

    def connect(self):
        return self.connection


def test_usage_store_scopes_query_to_latest_host_binding_and_principal() -> None:
    store = PostgresUsageEvidenceStore("postgresql://unused", deployment_namespace="cloud")
    database = _Database()
    store._database = database
    context = HostContextEnvelope(
        grant_id="grant", host_app_id="trench", namespace_id="ws", workspace_ref="ws",
        resource_refs=(HostResourceRef(type="principal", id="alice"),),
        scopes=("event.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=100, max_model_tokens=1000, max_artifact_bytes=1000,
        ),
        origin="https://trench.example.com", policy_version="v1",
    )
    start = datetime(2026, 10, 1, tzinfo=UTC)
    assert store.read(context, start=start, end=start) == []
    assert "DISTINCT ON (task_id)" in database.connection.sql
    assert "host_app_id" in database.connection.sql
    assert "namespace_id" in database.connection.sql
    assert "workspace_ref" in database.connection.sql
    assert database.connection.params[:4] == ("cloud", "trench", "ws", "ws")
    assert json.loads(database.connection.params[4]) == [
        {"resource_type": "principal", "resource_id": "alice"}
    ]
