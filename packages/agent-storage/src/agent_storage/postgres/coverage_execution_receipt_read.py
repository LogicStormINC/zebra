"""Native receipt facts, not command, Host or publication authorization.

Caller must hold the native run/stream boundary (or a revalidated RR snapshot).
Never retain the result across transactions. Consumers still need qualified
verification, current Task/Host/fence/STOP/tail and exact command approval gates.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_core.application.coverage_executor import MAX_UNITS
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import CoverageModelBudgetState
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import SessionEvent

from agent_storage.postgres.coverage_execution_receipts import MAX_WITNESS_BYTES, model_fingerprint
from agent_storage.postgres.coverage_execution_source_migration import (
    COVERAGE_EXECUTION_SOURCE_MIGRATION,
)
from agent_storage.postgres.coverage_model_revision import model_revision
from agent_storage.postgres.coverage_model_source import MODEL_TYPES


@dataclass(frozen=True)
class ExecutionReceiptFacts:
    event: SessionEvent
    expected_count: int
    expected_digest: str
    accepted_count: int
    budget: CoverageModelBudgetState
    valid_until: datetime
    receipt_digest: str
    verifier_contract: str | None
    model_work_remaining: bool | None


def read_execution_receipt(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    *, _unchanged_model: bool = False,
) -> ExecutionReceiptFacts | None:
    """Three native reads; missing legacy witness is distinct from corrupt witness.

    New witnesses bind v87's transactionally maintained generation/revision;
    legacy witnesses retain O(history) fingerprint verification. No history
    arrays or historical object bodies are loaded. This does not replace fresh
    authorization, new-delta validation, recovery or independent certification.
    """
    tail = (
        """EXISTS (SELECT 1 FROM session_events t
          WHERE t.deployment_namespace=e.deployment_namespace AND t.session_id=e.session_id
            AND t.payload->>'namespace'=e.payload->>'namespace'
            AND t.payload->>'run_id'=e.payload->>'run_id'
            AND t.event_type=ANY(%s) AND t.sequence>e.sequence)"""
        if _unchanged_model else "FALSE"
    )
    row = connection.execute(
        f"""SELECT CASE WHEN size.bytes<=%s THEN to_jsonb(e) END AS source,
           CASE WHEN size.bytes<=%s THEN r.body END AS body,
           r.body_digest,r.namespace,r.run_id,
           r.session_id,r.sequence,r.predecessor_event_id,
           CASE WHEN size.bytes<=%s THEN p.body END AS previous_body,
           CASE WHEN size.bytes<=%s THEN to_jsonb(pe) END AS previous_source,
           p.body_digest AS previous_digest,size.bytes AS witness_bytes,
           EXISTS (SELECT 1 FROM zebra_schema_migrations
             WHERE version=%s AND name=%s AND checksum=%s) AS source_sealed,
           {tail} AS model_tail
           FROM session_events e LEFT JOIN coverage_execution_receipts r
             ON r.deployment_namespace=e.deployment_namespace AND r.event_id=e.event_id
           LEFT JOIN coverage_execution_receipts p
             ON p.deployment_namespace=r.deployment_namespace AND p.event_id=r.predecessor_event_id
           LEFT JOIN session_events pe
             ON pe.deployment_namespace=p.deployment_namespace AND pe.event_id=p.event_id
           CROSS JOIN LATERAL (SELECT octet_length(to_jsonb(e)::text)
             +coalesce(octet_length(r.body::text),0)
             +coalesce(octet_length(p.body::text),0)
             +coalesce(octet_length(to_jsonb(pe)::text),0) AS bytes) size
           WHERE e.deployment_namespace=%s AND e.session_id=%s
             AND e.payload->>'namespace'=%s AND e.payload->>'run_id'=%s
             AND e.event_type='coverage_batch_accepted' ORDER BY e.sequence DESC LIMIT 1""",
        (MAX_WITNESS_BYTES, MAX_WITNESS_BYTES, MAX_WITNESS_BYTES, MAX_WITNESS_BYTES,
         COVERAGE_EXECUTION_SOURCE_MIGRATION.version, COVERAGE_EXECUTION_SOURCE_MIGRATION.name,
         COVERAGE_EXECUTION_SOURCE_MIGRATION.checksum,
         *((list(MODEL_TYPES),) if _unchanged_model else ()),
         deployment, binding.session_id, binding.namespace, binding.run_id),
    ).fetchone()
    if row is None or row["body_digest"] is None:
        return None  # Initial/legacy/native acceptance without a witness, never backfill.
    if _unchanged_model and row["model_tail"]:
        return None  # New native MODEL work requires full replay, not stale budget reuse.
    if not row["source_sealed"] or row["witness_bytes"] > MAX_WITNESS_BYTES:
        raise ValueError("execution receipt source retention/capacity prerequisite failed")
    try:
        return _validate(connection, deployment, binding, row)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("execution receipt is malformed") from error


def _count(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_UNITS:
        raise ValueError("execution receipt count is invalid")
    return value


def _validate(
    connection: Any, deployment: str, binding: CoverageRunBinding, row: Any,
) -> ExecutionReceiptFacts:
    body = row["body"]
    remaining = body.get("model_work_remaining")
    if remaining is not None and type(remaining) is not bool:
        raise ValueError("execution receipt remaining model predicate is invalid")
    event = SessionEvent.model_validate(row["source"])
    if (
        type(body) is not dict or coverage_digest(body) != row["body_digest"]
        or body["protocol"] != "coverage-execution-receipt/1"
        or body["deployment_namespace"] != deployment
        or body["binding"] != binding.model_dump(mode="json")
        or body["accepted_event"] != event.model_dump(mode="json")
        or (row["namespace"], row["run_id"], row["session_id"], row["sequence"])
        != (binding.namespace, binding.run_id, binding.session_id, event.sequence)
    ):
        raise ValueError("execution receipt differs from its exact native source/binding")
    expected, accepted = _count(body["expected_count"]), _count(body["accepted_count"])
    delta = _count(event.payload["result_count"])
    digest = body["expected_digest"]
    if not 0 < delta <= accepted <= expected or (
        type(digest) is not str or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("execution receipt has invalid unit identity/progress")
    budget = CoverageModelBudgetState.model_validate(body["budget"])
    if budget.unresolved or budget.policy.validation_mode != "final_certification":
        raise ValueError("execution receipt has unresolved or ineligible model budget")
    command = body["command"]
    pending, handoff = command["pending"], command["receipt"]
    if (
        handoff["status"] != "accepted" or handoff["handled_event_id"] is not None
        or pending["status"] != "pending"
        or any(type(value) is not int or value < 0 for value in
               (pending["accepted_sequence"], pending["current_generation"],
                handoff["wake_generation"]))
        or handoff["wake_generation"] != pending["current_generation"]
        or type(handoff["execution_floor_sequence"]) is not int
        or not pending["accepted_sequence"] <= handoff["execution_floor_sequence"] < event.sequence
        or any(handoff[k] != pending[k] for k in
               ("accepted_event_id", "command_id", "session_id", "scope_key"))
        or handoff["session_id"] != str(binding.session_id)
        or any(handoff[k] != event.payload["fence"][k] for k in
               ("control_plane_epoch", "fencing_token", "owner_instance_id"))
    ):
        raise ValueError("execution receipt producing command/fence conflicts")
    deadline = datetime.fromisoformat(body["valid_until"])
    previous = row["previous_body"]
    if row["predecessor_event_id"] is None:
        if body["predecessor_event_id"] is not None or body["predecessor_digest"] is not None:
            raise ValueError("execution receipt root predecessor conflicts")
        prior_count = 0
    else:
        if (
            type(previous) is not dict or coverage_digest(previous) != row["previous_digest"]
            or previous["accepted_event"] != SessionEvent.model_validate(
                row["previous_source"]
            ).model_dump(mode="json")
            or body["predecessor_digest"] != row["previous_digest"]
            or body["predecessor_event_id"] != str(row["predecessor_event_id"])
            or previous["accepted_event"]["event_id"] != body["predecessor_event_id"]
            or previous["accepted_event"]["sequence"] >= event.sequence
            or previous["binding"] != body["binding"]
            or previous["expected_count"] != expected or previous["expected_digest"] != digest
            or previous["budget"]["policy"] != body["budget"]["policy"]
            or previous.get("verifier_contract") != body.get("verifier_contract")
            or previous["command"]["pending"]["accepted_event_id"] != pending["accepted_event_id"]
            or deadline > datetime.fromisoformat(previous["valid_until"])
        ):
            raise ValueError("execution receipt predecessor conflicts")
        prior_count = _count(previous["accepted_count"])
    if accepted != prior_count + delta:
        raise ValueError("execution receipt accepted count is not the validated chain delta")
    if deadline.utcoffset() is None or deadline > min(
        budget.policy.deadline, binding.snapshot.expires_at,
    ):
        raise ValueError("execution receipt original deadline conflicts")
    revision = body.get("model_revision")
    if revision is not None:
        if (type(revision) is not dict or set(revision) != {"generation", "revision"}
                or type(revision["revision"]) is not int or revision["revision"] <= 0
                or model_revision(connection, deployment, binding) != revision):
            raise ValueError(
                "execution receipt native model source/witness/budget changed (revision)"
            )
    else:
        fingerprint = model_fingerprint(connection, deployment, binding)
        if fingerprint is None or fingerprint != body["model_fingerprint"]:
            raise ValueError("execution receipt native model source/witness/budget changed")
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if not budget.policy.started_at <= now < deadline:
        raise ValueError("execution receipt original deadline expired")
    return ExecutionReceiptFacts(
        event, expected, digest, accepted, budget, deadline, row["body_digest"],
        body.get("verifier_contract"),
        remaining,
    )
