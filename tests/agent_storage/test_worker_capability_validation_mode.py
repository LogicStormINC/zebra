"""Pure qualification regression: v2 workers cannot satisfy the v3 requirement."""

import os

import pytest
from agent_storage.postgres.worker_capability import (
    STRICT_WORKER_CONTRACT,
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
    pin_worker_capability,
)

from tests.agent_storage.test_worker_capability_admission import Connection, Rows

OLD_CONTRACT = "cov-exec-01:model:bounded-multipart:same-session:v2"
DIGEST = "a" * 64


@pytest.mark.parametrize("require_process", [False, True])
def test_old_contract_is_rejected_before_database_qualification(require_process):
    connection = Connection()
    with pytest.raises(WorkerCapabilityLostError, match="unsupported strict Worker contract"):
        pin_worker_capability(
            connection, "test", contract=OLD_CONTRACT,
            configuration_digest=DIGEST, require_process=require_process,
        )
    assert connection.calls == []


@pytest.mark.parametrize("require_process", [False, True])
@pytest.mark.parametrize(
    "worker_contract,worker_digest,accepted",
    [(OLD_CONTRACT, DIGEST, False), (STRICT_WORKER_CONTRACT, "b" * 64, False),
     (STRICT_WORKER_CONTRACT, DIGEST, True)],
)
def test_qualification_requires_current_contract_and_matching_configuration(
    require_process, worker_contract, worker_digest, accepted
):
    class QualifiedConnection(Connection):
        def execute(self, sql, params=()):
            result = super().execute(sql, params)
            if "FROM worker_process_capabilities" in sql:
                assert "AND contract=%s" in sql and "AND configuration_digest=%s" in sql
                assert params[2:4] == (STRICT_WORKER_CONTRACT, DIGEST)
                if (worker_contract, worker_digest) != params[2:4]:
                    return Rows(None)
            return result

    connection = QualifiedConnection()
    proof = WorkerCapabilityLease(
        connection.process, connection.epoch, 1, connection.expires,
        attestation="c" * 64, local_pid=os.getpid(),
    )

    def pin():
        return pin_worker_capability(
            connection, "test", contract=STRICT_WORKER_CONTRACT,
            configuration_digest=DIGEST, consumer_capability=proof,
            require_process=require_process,
        )

    if accepted:
        assert pin().process_id == proof.process_id
    else:
        with pytest.raises(WorkerCapabilityLostError, match="live matching Worker capability"):
            pin()
