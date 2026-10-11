"""Indexed exact native facts; never cached authority or publication proof."""

from typing import Any

from agent_core.domain.coverage_model_budget import CoverageModelBudgetState, CoverageModelPolicy
from agent_core.domain.coverage_persistence import CoverageRunBinding

from agent_storage.postgres.coverage_model_summary_migration import (
    COVERAGE_MODEL_SUMMARY_MIGRATION as MIGRATION,
)


def summary_state(
    connection: Any, deployment: str, binding: CoverageRunBinding, policy: CoverageModelPolicy,
) -> CoverageModelBudgetState | None:
    row = connection.execute(
        """SELECT s.*,l.policy AS ledger_policy,l.calls AS ledger_calls,
           l.charged_tokens AS ledger_tokens,l.unresolved AS ledger_unresolved
           FROM coverage_model_summary s JOIN coverage_model_ledger l USING
             (deployment_namespace,namespace,run_id)
           WHERE s.deployment_namespace=%s AND s.namespace=%s AND s.run_id=%s
             AND NOT s.invalidated AND EXISTS (SELECT 1 FROM zebra_schema_migrations
               WHERE version=%s AND name=%s AND checksum=%s)""",
        (deployment, binding.namespace, binding.run_id,
         MIGRATION.version, MIGRATION.name, MIGRATION.checksum),
    ).fetchone()
    if row is None:
        return None  # Legacy or unsupported mutation: independent native scans remain.
    if (
        row["session_id"] != binding.session_id or row["policy"] != policy.model_dump(mode="json")
        or row["ledger_policy"] != row["policy"] or row["initialized"] != 1
        or row["reserved"] != row["calls"]
        or row["receipts"] != row["calls"] - row["unresolved"]
        or row["witnesses"] != row["initialized"] + row["reserved"] + row["receipts"]
        or (row["ledger_calls"], row["ledger_tokens"], row["ledger_unresolved"])
        != (row["calls"], row["charged_tokens"], row["unresolved"])
        or not 0 <= row["calls"] <= policy.max_calls
        or not 0 <= row["charged_tokens"] <= policy.max_tokens
        or not 0 <= row["unresolved"] <= row["calls"]
    ):
        raise ValueError("model counters/index conflict with exact incremental native facts")
    return CoverageModelBudgetState(
        policy=policy, calls=row["calls"], charged_tokens=row["charged_tokens"],
        unresolved=row["unresolved"],
    )
