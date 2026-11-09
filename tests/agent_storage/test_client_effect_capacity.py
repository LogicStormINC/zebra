"""Client-effect maintenance stays inside the composed DB identity and I/O budget."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

from agent_storage.postgres.capacity_profile import CapacityProfile
from agent_storage.postgres.client_effect_recovery import ClientEffectRecovery
from agent_storage.postgres.connection_capacity import (
    ConnectionBudget,
    capacity_for,
    capacity_scope,
)

from tests.agent_storage.test_postgres_connection_capacity import profile_data


def test_recovery_uses_original_authority_and_bounded_task_io(monkeypatch):
    budget = ConnectionBudget(
        "dbname=one", CapacityProfile.parse(json.dumps(profile_data())), "worker"
    )
    calls = []
    with capacity_scope(budget):
        recovery = ClientEffectRecovery("dbname=one", deployment_namespace="capacity-test")

        def connect():
            assert capacity_for(recovery._database._dsn) is budget
            calls.append(True)
            return nullcontext(
                SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchall=lambda: []))
            )

        monkeypatch.setattr(recovery._database, "connect_task_io", connect)
        assert recovery.reconcile() == 0
    assert calls == [True]
