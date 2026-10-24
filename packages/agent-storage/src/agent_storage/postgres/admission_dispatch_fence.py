"""Irreversible first-winner fence, only before admission dispatch, never a takeover."""

from dataclasses import replace
from typing import Any

from agent_storage.idempotency import IdempotencyConflictError, new_idempotency_record
from agent_storage.postgres.work_unit import postgres_transaction_work_unit

CLAIM = "client-admission-v1-claim"
FENCE = "client-admission-v1-dispatch-fence"
PROTOCOL = "pre-dispatch/1"


def admission_fence(store: Any, scoped: str, digest: str, *, terminate: bool) -> dict[str, str]:
    database = store._database
    with database.connect() as connection:
        # Indexed original row lock; no dispatch, network, or external effect in this transaction.
        claim = connection.execute(
            """SELECT request_hash,response_body FROM control_plane_idempotency_records
            WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s FOR UPDATE""",
            (database.deployment_namespace, CLAIM, scoped),
        ).fetchone()
        if claim is None:
            return {"state": "not_observed", "recorded_at": ""}
        if claim["request_hash"] != digest:
            raise IdempotencyConflictError("original admission differs")
        if claim["response_body"].get("dispatch_protocol") != PROTOCOL:
            return {"state": "unsupported", "recorded_at": ""}
        with postgres_transaction_work_unit(database, connection):
            existing = store.get(action=FENCE, idempotency_key=scoped)
            if existing is not None:
                return {
                    "state": existing.response_body["state"],
                    "recorded_at": existing.created_at.isoformat(),
                }
            # ponytail: started is irreversible even if the process dies before its first
            # effect. Stronger post-start proof needs atomic dispatch, never lease expiry.
            record = store.save(
                replace(
                    new_idempotency_record(
                        action=FENCE,
                        idempotency_key=scoped,
                        request_hash=digest,
                        status_code=200,
                        response_body={"state": "terminated" if terminate else "started"},
                    ),
                    created_at=connection.execute("SELECT clock_timestamp() AS now").fetchone()[
                        "now"
                    ],
                )
            )
            # The persisted record timestamp is returned verbatim on future reads.
            return {
                "state": record.response_body["state"],
                "recorded_at": record.created_at.isoformat(),
            }
