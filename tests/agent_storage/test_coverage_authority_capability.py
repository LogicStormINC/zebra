"""Old fleets and schemas cannot claim the versioned authority execution contract."""
# ruff: noqa: F811

from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_storage.postgres import migration_runner
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities
from agent_storage.worker_capability_configuration import continuation_configuration_digest

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn  # noqa: F401


@pytest.fixture(autouse=True)
def legacy_schema(request, monkeypatch):
    if request.node.name == "test_missing_migration_uses_explicit_legacy_path":
        monkeypatch.setattr(migration_runner, "MIGRATIONS", tuple(
            m for m in migration_runner.MIGRATIONS if m.version < 90
        ))


def test_v89_consumer_identity_cannot_register_the_new_contract():
    configuration = "a" * 64
    old = coverage_digest({
        "configuration": configuration, "consumer": "coverage-execution-receipt/1",
        "producer": "native-semantic-commit:execution-receipt/1",
        "model_proof": "database-maintained-model-revision/87",
        "model_budget": "database-maintained-model-summary/88",
        "task_admission": "database-maintained-task-summary/89",
    })
    assert continuation_configuration_digest(configuration) != old
    store = PostgresWorkerCapabilities("dbname=unused", deployment_namespace="fixture")
    with pytest.raises(ValueError, match="continuation qualification"):
        store.register(uuid4(), configuration_digest=configuration, continuation_digest=old)


def test_missing_migration_uses_explicit_legacy_path(model_cloud):
    env = model_cloud
    load = Mock(side_effect=AssertionError("qualified context must not be prepared"))
    assert PostgresCoverageAuthority.prepare(
        env.database, env.session, env.task_binding, env.fence, load,
    ) is None
    load.assert_not_called()
