"""Atomic processing witnesses. Not yet a handoff or publication authorization.

Only the validated commit transaction writes these; projection rebuild never does.
The future normal-handoff reader must validate current authority and native source
fingerprints, plus its versioned consumer capability, before using a witness.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import CoverageModelBudgetState
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.events import SessionEvent
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_model_revision import model_revision
from agent_storage.postgres.coverage_model_source import MODEL_TYPES

MAX_WITNESS_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class VerifiedCommitFacts:
    """Invocation-local facts from the successful configured derivation verifier."""

    state: CoverageModelBudgetState
    expected_count: int
    expected_digest: str
    model_work_remaining: bool
    verifier_contract: str | None = None


def model_fingerprint(connection: Any, deployment: str, binding: CoverageRunBinding) -> str | None:
    """One bounded native scan binds Events, independent witnesses, calls and ledger.

    ponytail: O(history) native fingerprint, not an immutable Merkle root. This is
    dormant receipt groundwork; native source-root retention is the upgrade path.
    No object bytes or Python history arrays are loaded here.
    """
    scope = (deployment, binding.namespace, binding.run_id)
    row = connection.execute(
        """SELECT * FROM (WITH bodies AS MATERIALIZED (
           SELECT 'event' AS kind,sequence::text AS key,to_jsonb(e)::text AS body
           FROM session_events e WHERE deployment_namespace=%s AND session_id=%s
             AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)
           UNION ALL SELECT 'witness',sequence::text,to_jsonb(w)::text
           FROM coverage_model_events w WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
           UNION ALL SELECT 'call',reservation_key,to_jsonb(c)::text
           FROM coverage_model_calls c WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
           UNION ALL SELECT 'ledger','',to_jsonb(l)::text
           FROM coverage_model_ledger l WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
           ), bounds AS (SELECT count(*) AS count,coalesce(sum(octet_length(body)),0) AS bytes
             FROM bodies)
           SELECT bounds.*,proof.digest FROM bounds LEFT JOIN LATERAL (
             SELECT encode(sha256(convert_to(coalesce(
               string_agg(jsonb_build_array(kind,key,body)::text,E'\\n' ORDER BY kind,key),''),
               'UTF8')),'hex') AS digest
             FROM bodies WHERE bounds.bytes<=%s AND bounds.count<=800003
           ) proof ON TRUE) AS native_fingerprint""",
        (deployment, binding.session_id, binding.namespace, binding.run_id, list(MODEL_TYPES),
         *scope, *scope, *scope, MAX_WITNESS_BYTES),
    ).fetchone()
    if row["count"] == 0 or row["bytes"] > MAX_WITNESS_BYTES or row["count"] > 800003:
        return None  # Receipt capacity is not a new acceptance/publication budget.
    return str(row["digest"])


def mint_execution_receipt(
    connection: Any, deployment: str, binding: CoverageRunBinding, event: SessionEvent,
    facts: VerifiedCommitFacts, *, valid_until: datetime, verifier_contract: str | None = None,
) -> None:
    """Caller holds run/stream locks after all acceptance and current-fence gates.

    Old prefixes with no receipt and commands outside native handoff stay legacy.
    No backfill from progress projections, and no receipt on duplicate retries.
    """
    if verifier_contract is not None and facts.verifier_contract != verifier_contract:
        return  # A composition string never qualifies an arbitrary derivation callback.
    scope = (deployment, binding.namespace, binding.run_id)
    command_rows = connection.execute(
        """SELECT to_jsonb(p) AS pending,to_jsonb(r) AS receipt
           FROM session_command_pending p JOIN command_handoff_receipts r
             ON r.deployment_namespace=p.deployment_namespace
               AND r.accepted_event_id=p.accepted_event_id
           WHERE p.deployment_namespace=%s AND p.session_id=%s AND p.status='pending'
             AND r.status='accepted' AND r.handled_event_id IS NULL LIMIT 2""",
        (deployment, binding.session_id),
    ).fetchall()
    if len(command_rows) != 1:
        return
    command = command_rows[0]
    pending, handoff = command["pending"], command["receipt"]
    fence = event.payload["fence"]
    if (
        handoff["wake_generation"] != pending["current_generation"]
        or handoff["execution_floor_sequence"] is None
        or handoff["execution_floor_sequence"] >= event.sequence
        or any(handoff[name] != fence[name] for name in
               ("control_plane_epoch", "fencing_token", "owner_instance_id"))
    ):
        raise ValueError("execution receipt current command/fence conflicts")
    previous = connection.execute(
        """SELECT e.event_id,e.sequence,to_jsonb(e) AS source,w.body,w.body_digest
           FROM session_events e LEFT JOIN coverage_execution_receipts w
             ON w.deployment_namespace=e.deployment_namespace AND w.event_id=e.event_id
           WHERE e.deployment_namespace=%s AND e.session_id=%s
             AND e.payload->>'namespace'=%s AND e.payload->>'run_id'=%s
             AND e.event_type='coverage_batch_accepted' AND e.sequence<%s
           ORDER BY e.sequence DESC LIMIT 1""",
        (deployment, binding.session_id, binding.namespace, binding.run_id, event.sequence),
    ).fetchone()
    binding_body = binding.model_dump(mode="json")
    predecessor = previous["body"] if previous else None
    if previous is not None and predecessor is None:
        return  # Legacy prefix: full recovery remains mandatory, never synthesize a root.
    if predecessor is not None and predecessor.get("verifier_contract") != verifier_contract:
        return  # Never qualify an old prefix by switching the current verifier.
    if predecessor is not None and (
        coverage_digest(predecessor) != previous["body_digest"]
        or predecessor["binding"] != binding_body
        or predecessor["accepted_event"] != SessionEvent.model_validate(
            previous["source"]
        ).model_dump(mode="json")
        or predecessor["expected_count"] != facts.expected_count
        or predecessor["expected_digest"] != facts.expected_digest
        or predecessor["budget"]["policy"] != facts.state.policy.model_dump(mode="json")
        or predecessor["command"]["pending"]["accepted_event_id"] != pending["accepted_event_id"]
    ):
        raise ValueError("execution receipt predecessor differs from native acceptance")
    accepted_count = (
        (predecessor["accepted_count"] if predecessor else 0) + event.payload["result_count"]
    )
    if not 0 < accepted_count <= facts.expected_count:
        raise ValueError("execution receipt exact accepted count conflicts")
    revision = model_revision(connection, deployment, binding)
    # ponytail: the caller already verified native MODEL facts under run/stream
    # locks. v87 seals that exact transaction state; hashing history again adds
    # no integrity guarantee. Legacy consumers fail closed on a null fingerprint.
    fingerprint = (
        model_fingerprint(connection, deployment, binding) if revision is None else None
    )
    if revision is None and fingerprint is None:
        return  # Safe legacy/full-recovery fallback, not an integrity-error downgrade.
    if predecessor is not None:
        valid_until = min(valid_until, datetime.fromisoformat(predecessor["valid_until"]))
    body = {
        "protocol": "coverage-execution-receipt/1", "deployment_namespace": deployment,
        "binding": binding_body,
        "accepted_event": event.model_dump(mode="json"),
        "predecessor_event_id": str(previous["event_id"]) if previous else None,
        "predecessor_digest": previous["body_digest"] if previous else None,
        "expected_count": facts.expected_count, "expected_digest": facts.expected_digest,
        "accepted_count": accepted_count, "budget": facts.state.model_dump(mode="json"),
        "model_fingerprint": fingerprint,
        "model_revision": revision,
        "command": command, "valid_until": valid_until.isoformat(),
        "verifier_contract": verifier_contract,
        "model_work_remaining": facts.model_work_remaining,
    }
    connection.execute(
        """INSERT INTO coverage_execution_receipts
           (deployment_namespace,namespace,run_id,session_id,event_id,sequence,
            predecessor_event_id,body,body_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (*scope, binding.session_id, event.event_id, event.sequence,
         previous["event_id"] if previous else None, Jsonb(body), coverage_digest(body)),
    )
