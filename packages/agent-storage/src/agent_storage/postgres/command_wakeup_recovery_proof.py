"""Generation approval checks shared by relay and execution handoff."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from agent_core.application.coverage_executor import MAX_UNITS
from agent_core.contracts.broker_envelope import ZebraCommandEnvelope
from agent_core.domain.coverage_contracts import coverage_digest

from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES

CoverageRecoveryCheck = Callable[[Any, str, dict[str, Any], dict[str, Any]], dict[str, Any]]
MAX_TOTAL_AGE = timedelta(hours=24)
MAX_GENERATION = 5


def verified_coverage_recovery(
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    receipt: dict[str, Any] | None,
    check: CoverageRecoveryCheck | None,
) -> dict[str, Any]:
    """One configured native proof, re-read both at approval and at handoff.

    Missing composition is refusal, not permission to classify ordinary Events.
    The checker must prove current external source authority and governed bytes;
    this shared boundary pins the exact command/floor/generation independently.
    """
    if receipt is None or not callable(check):
        raise ValueError("strict recovery requires configured native checkpoint proof")
    floor = receipt["execution_floor_sequence"]
    if (
        receipt["status"] != "accepted"
        or receipt["handled_event_id"] is not None
        or type(floor) is not int
        or floor < pending["accepted_sequence"]
        or any(
            receipt[name] != pending[name]
            for name in ("scope_key", "command_id", "session_id", "accepted_event_id")
        )
        or pending["current_generation"]
        not in (receipt["wake_generation"], receipt["wake_generation"] + 1)
    ):
        raise ValueError("strict recovery command receipt boundary conflicts")
    stream = connection.execute(
        "SELECT current_version FROM session_streams "
        "WHERE deployment_namespace=%s AND session_id=%s FOR UPDATE",
        (namespace, pending["session_id"]),
    ).fetchone()
    if stream is None or stream["current_version"] < floor:
        raise ValueError("strict recovery stream floor is unavailable")
    if receipt["started_event_id"] is not None:
        started = connection.execute(
            "SELECT sequence,event_type FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s AND event_id=%s",
            (namespace, pending["session_id"], receipt["started_event_id"]),
        ).fetchone()
        if (
            started is None
            or started["event_type"] != "harness_attempt_started"
            or not floor < started["sequence"] <= stream["current_version"]
        ):
            raise ValueError("strict recovery started boundary conflicts")
    proof = check(connection, namespace, pending, receipt)
    boundary = {
        "session_id": str(pending["session_id"]),
        "accepted_event_id": str(pending["accepted_event_id"]),
        "generation": receipt["wake_generation"],
        "floor": floor,
        "stream_revision": stream["current_version"],
        "receipt_digest": coverage_digest(
            {
                key: value if value is None or isinstance(value, str | int) else str(value)
                for key, value in receipt.items()
            }
        ),
    }
    if type(proof) is not dict or any(proof.get(key) != value for key, value in boundary.items()):
        raise ValueError("strict recovery configured proof changed its native boundary")
    check_coverage_recovery_clock(connection, proof, pending=pending)
    return proof


def check_coverage_recovery_clock(
    connection: Any, proof: dict[str, Any], *, pending: dict[str, Any] | None = None
) -> None:
    deadline = datetime.fromisoformat(proof["valid_until"])
    if pending is not None and "created_at" in pending:
        deadline = min(deadline, pending["created_at"] + MAX_TOTAL_AGE)
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if deadline.utcoffset() is None or now >= deadline:
        raise ValueError("strict recovery proof expired before final native clock")


def coverage_progress(proof: dict[str, Any]) -> tuple[int, int]:
    expected, accepted = proof["expected_count"], proof["accepted_count"]
    digest = proof["expected_digest"]
    if (
        type(expected) is not int
        or not 0 <= expected <= MAX_UNITS
        or type(accepted) is not int
        or not 0 <= accepted <= expected
        or type(digest) is not str
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("strict recovery requires bounded immutable unit progress")
    return expected, accepted


def coverage_generation_usage(
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    proof: dict[str, Any],
    *,
    maximum_crashes: int,
) -> tuple[int, int]:
    """Audit native approvals; progress wakes never spend the crash allowance.

    ponytail: bounded O(n) audit, no new mutable counter/migration or digest cache.
    The current configured checker already verified every canonical batch body;
    historical counters must equal those authoritative Event prefixes as well.
    """
    expected, accepted = coverage_progress(proof)
    bound = expected + maximum_crashes
    generation = pending["current_generation"]
    if type(generation) is not int or not 0 <= generation <= bound:
        raise ValueError("strict recovery generations exceed progress/crash bound")
    scope = (namespace, pending["accepted_event_id"])
    rows = connection.execute(
        "SELECT a.*,count(*) OVER () AS history_count,"
        "sum(octet_length(to_jsonb(a)::text)) OVER () AS history_bytes "
        "FROM command_recovery_attempts a WHERE deployment_namespace=%s "
        "AND accepted_event_id=%s ORDER BY wake_generation LIMIT %s",
        (*scope, bound + 1),
    ).fetchall()
    if (rows[0]["history_count"] if rows else 0) != generation or (
        rows and rows[0]["history_bytes"] > MAX_COVERAGE_ARTIFACT_BYTES
    ):
        raise ValueError("strict recovery approval history is missing or exceeds bounds")
    crashes, previous = 0, 0
    prefixes: dict[int, int] = {}
    for index, row in enumerate(rows, 1):
        if row["wake_generation"] != index:
            raise ValueError("strict recovery approval generation has a gap")
        old = row["coverage_proof"]
        if old is not None:
            old_expected, old_accepted = coverage_progress(old)
            if (
                old_expected != expected
                or not previous <= old_accepted <= accepted
                or any(
                    old.get(k) != proof[k]
                    for k in (
                        "session_id",
                        "accepted_event_id",
                        "run_id",
                        "namespace",
                        "task_binding_digest",
                        "expected_digest",
                    )
                )
                or old["generation"] != index - 1
                or old["stream_revision"] != row["approved_stream_sequence"]
                or type(old["source_watermark"]) is not int
                or not 0 <= old["source_watermark"] <= proof["source_watermark"]
            ):
                raise ValueError("strict recovery approval changed its frozen progress proof")
            watermark = old["source_watermark"]
            if watermark in prefixes and prefixes[watermark] != old_accepted or (
                row["reason"] == "coverage_continuation" and not previous < old_accepted < expected
            ):
                raise ValueError("strict recovery continuation has no new canonical accepted units")
            prefixes[watermark] = old_accepted
            previous = old_accepted
        elif row["reason"] in {"coverage_continuation", "coverage_checkpoint"}:
            raise ValueError("strict recovery approval has no coverage proof")
        if row["reason"] != "coverage_continuation":
            crashes += 1
    if prefixes != _accepted_prefix_counts(connection, namespace, pending, proof, prefixes):
        raise ValueError("strict recovery continuation has no new canonical accepted units")
    if crashes > maximum_crashes:
        raise ValueError("strict recovery crash allowance exceeded")
    return crashes, previous


def _accepted_prefix_counts(
    connection: Any, namespace: str, pending: dict[str, Any], proof: dict[str, Any],
    prefixes: dict[int, int],
) -> dict[int, int]:
    if not prefixes:
        return {}
    # One ordered scan, not a correlated SUM per generation. Cutoffs sort after
    # batch deltas at the same sequence, preserving the old inclusive <= boundary.
    rows = connection.execute(
        """WITH deltas AS (
             SELECT sequence,false AS cutoff,(payload->>'result_count')::bigint AS units
             FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND payload->>'namespace'=%s AND payload->>'run_id'=%s
               AND event_type='coverage_batch_accepted' AND sequence<=%s
             UNION ALL SELECT watermark,true,0 FROM unnest(%s::bigint[]) AS c(watermark)
           ), prefixes AS (
             SELECT sequence,cutoff,sum(units) OVER (
               ORDER BY sequence,cutoff ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
             ) AS count FROM deltas
           ) SELECT sequence AS watermark,coalesce(count,0) AS count
             FROM prefixes WHERE cutoff""",
        (namespace, pending["session_id"], proof["namespace"], proof["run_id"],
         max(prefixes), sorted(prefixes)),
    ).fetchall()
    return {row["watermark"]: int(row["count"]) for row in rows}


def recovery_approval(connection: Any, envelope: ZebraCommandEnvelope) -> dict[str, Any] | None:
    if envelope.wake_generation == 0:
        return None
    row: dict[str, Any] | None = connection.execute(
        """SELECT * FROM command_recovery_attempts WHERE deployment_namespace = %s
           AND accepted_event_id = %s AND wake_generation = %s""",
        (envelope.deployment_namespace, envelope.accepted_event_id, envelope.wake_generation),
    ).fetchone()
    if (
        row is None
        or str(row["message_id"]) != envelope.message_id
        or str(row["previous_message_id"]) != envelope.causation_id
    ):
        raise ValueError("missing or mismatched command recovery approval")
    return row
