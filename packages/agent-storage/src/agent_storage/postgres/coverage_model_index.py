"""Exact incremental native facts with independent legacy integrity-scan fallback."""

from types import EllipsisType
from typing import Any

from agent_core.domain.coverage_model_budget import CoverageModelBudgetState, CoverageModelPolicy
from agent_core.domain.coverage_persistence import CoverageRunBinding
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_model_source import MODEL_TYPES, params, task_policy
from agent_storage.postgres.coverage_model_summary import summary_state


def indexed_state(
    connection: Any, deployment: str, binding: CoverageRunBinding,
    *, _policy: CoverageModelPolicy | None | EllipsisType = ...,
) -> CoverageModelBudgetState:
    policy = (
        task_policy(connection, deployment, binding, incremental=True)
        if _policy is ... else _policy
    )
    if policy is not None and policy.validation_mode == "final_certification":
        summary = summary_state(connection, deployment, binding, policy)
        if summary is not None:
            return summary
    ledger = connection.execute(
        """SELECT * FROM coverage_model_ledger WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s""",
        params(deployment, binding),
    ).fetchone()
    if policy is None or ledger is None:
        raise ValueError("model ledger is not initialized")
    if ledger["policy"] != policy.model_dump(mode="json"):
        raise ValueError("frozen model policy conflicts with actual Task admission")
    # ponytail: legacy/unsupported mutation stays O(history); never bless an
    # invalidated summary from mutable projections. New normal transitions use
    # v88 exact native facts above; independent recovery/certification remain full.
    conflict = connection.execute(
        """WITH source AS (SELECT sequence,to_jsonb(e) AS body FROM session_events e
           WHERE deployment_namespace=%s AND session_id=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)),
           witness AS (SELECT sequence,source_row FROM coverage_model_events
           WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s)
           SELECT 1 FROM source FULL JOIN witness USING(sequence)
           WHERE body IS DISTINCT FROM source_row LIMIT 1""",
        (
            deployment,
            binding.session_id,
            binding.namespace,
            binding.run_id,
            list(MODEL_TYPES),
            *params(deployment, binding),
        ),
    ).fetchone()
    if conflict:
        raise ValueError("model source Event missing/tampered or witness missing")
    facts = connection.execute(
        """SELECT count(*) AS calls,
           coalesce(sum(CASE WHEN receipt IS NULL THEN (reservation->>'token_bound')::bigint
             ELSE (receipt->>'total_tokens')::bigint END),0) AS charged_tokens,
           count(*) FILTER (WHERE receipt IS NULL) AS unresolved,
           bool_or(r.event_type IS DISTINCT FROM 'coverage_model_call_reserved'
             OR r.payload->'reservation' IS DISTINCT FROM c.reservation
             OR (c.receipt IS NOT NULL AND (
               u.event_type IS DISTINCT FROM 'coverage_model_usage_recorded'
               OR u.payload->'receipt' IS DISTINCT FROM c.receipt))
             OR (c.receipt IS NULL AND c.receipt_sequence IS NOT NULL)) AS conflict
           FROM coverage_model_calls c
           LEFT JOIN session_events r ON r.deployment_namespace=c.deployment_namespace
             AND r.session_id=%s AND r.sequence=c.reserved_sequence
           LEFT JOIN session_events u ON u.deployment_namespace=c.deployment_namespace
             AND u.session_id=%s AND u.sequence=c.receipt_sequence
           WHERE c.deployment_namespace=%s AND c.namespace=%s AND c.run_id=%s""",
        (binding.session_id, binding.session_id, *params(deployment, binding)),
    ).fetchone()
    source_counts = connection.execute(
        """SELECT count(*) FILTER (
             WHERE event_type='coverage_model_budget_initialized') AS initialized,
           count(*) FILTER (WHERE event_type='coverage_model_call_reserved') AS reserved,
           count(*) FILTER (WHERE event_type='coverage_model_usage_recorded') AS receipts,
           bool_or(event_type='coverage_model_budget_initialized'
             AND payload->'policy'<>%s) AS conflict
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)""",
        (
            Jsonb(ledger["policy"]),
            deployment,
            binding.session_id,
            binding.namespace,
            binding.run_id,
            list(MODEL_TYPES),
        ),
    ).fetchone()
    if (
        facts["conflict"]
        or source_counts["conflict"]
        or source_counts["initialized"] != 1
        or source_counts["reserved"] != facts["calls"]
        or source_counts["receipts"] != facts["calls"] - facts["unresolved"]
        or any(ledger[field] != facts[field] for field in ("calls", "charged_tokens", "unresolved"))
        or facts["calls"] > policy.max_calls
        or facts["charged_tokens"] > policy.max_tokens
    ):
        raise ValueError("model counters/index conflict with exact source Events")
    return CoverageModelBudgetState(
        policy=policy,
        calls=facts["calls"],
        charged_tokens=int(facts["charged_tokens"]),
        unresolved=facts["unresolved"],
    )


def indexed_call(connection: Any, deployment: str, binding: CoverageRunBinding, key: str) -> Any:
    return connection.execute(
        """SELECT * FROM coverage_model_calls WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s AND reservation_key=%s""",
        (*params(deployment, binding), key),
    ).fetchone()
