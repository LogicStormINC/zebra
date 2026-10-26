"""Read-only original message observation across namespace and independent processes."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_storage import new_idempotency_record
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from zebra_agent_api.idempotency import request_hash
from zebra_agent_api.task_message_receipts import read_task_message_receipt

from tests.agent_storage.test_postgres_client_effects import stores as stores

pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEBRA_TEST_POSTGRES_DSN"), reason="owned PG required"
)


def test_original_message_record_read_is_namespace_scoped_and_cross_process(request):
    *_, dsn, namespace = request.getfixturevalue("stores")
    storage = PostgresIdempotencyStore(dsn, deployment_namespace=namespace)
    task, key = str(uuid4()), str(uuid4())
    app = SimpleNamespace(stores=SimpleNamespace(idempotency=storage))
    assert (
        read_task_message_receipt(app, task, {"Idempotency-Key": key}).body["status"]
        == "not_observed"
    )
    body = {"role": "user", "content": "保留原始消息 😀"}
    response = {"rolled_over": True, "task_id": task, "idempotency_key": key}
    storage.save(
        new_idempotency_record(
            action=f"task-message:{task}",
            idempotency_key=key,
            request_hash=request_hash(body),
            status_code=201,
            response_body=response,
        )
    )

    def rows():
        with psycopg.connect(dsn) as conn:
            return conn.execute(
                "SELECT row_to_json(r)::text FROM control_plane_idempotency_records r "
                "WHERE deployment_namespace=%s ORDER BY action,idempotency_key",
                (namespace,),
            ).fetchall()

    before = rows()
    code = """import json,os,sys
from types import SimpleNamespace
from agent_storage.postgres.idempotency import PostgresIdempotencyStore
from zebra_agent_api.task_message_receipts import read_task_message_receipt
store=PostgresIdempotencyStore(os.environ['OWNED_RECEIPT_DSN'],deployment_namespace=os.environ['OWNED_RECEIPT_NAMESPACE'])
result=read_task_message_receipt(SimpleNamespace(stores=SimpleNamespace(idempotency=store)),sys.argv[1],{'Idempotency-Key':sys.argv[2]})
print(json.dumps({'code':result.status_code,'body':result.body}))
"""
    for ns in (namespace, "other-" + namespace, namespace):
        result = json.loads(
            subprocess.check_output(
                [sys.executable, "-c", code, task, key],
                text=True,
                env={**os.environ, "OWNED_RECEIPT_DSN": dsn, "OWNED_RECEIPT_NAMESPACE": ns},
                timeout=10,
            )
        )
        assert result["code"] == 200
        if ns == namespace:
            assert result["body"]["request_hash"] == request_hash(body)
            assert result["body"]["response"] == {"status_code": 201, "body": response}
        else:
            assert result["body"]["status"] == "not_observed"
            assert result["body"]["noncommit_proved"] is False
    assert rows() == before
