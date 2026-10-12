"""Untrusted routing pointers for one bounded acceptance; locked kernels prove them again."""

from typing import Any

from agent_core.application.coverage_executor import observation_id
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.identifiers import ArtifactId
from agent_core.ports.coverage import CoverageCommit

from agent_storage.postgres.coverage_artifacts import _identity
from agent_storage.postgres.coverage_model_replay_rows import indexed_calls


class CoverageEvidenceUnavailable(ValueError):
    """Pre-I/O native eligibility refusal; callers retain guarded public operations."""


def acceptance_evidence_ids(
    connection: Any, deployment: str, binding: CoverageRunBinding, request: CoverageCommit,
) -> tuple[ArtifactId, ...]:
    record_ids = sorted({item.key.record_id for item in request.results})
    identifiers = {_identity(binding.snapshot.manifest_artifact_ref),
                   _identity(request.result_artifact_ref)}
    identifiers.update(observation_id(binding, item.key) for item in request.results)

    def bounded() -> None:
        if len(identifiers) > 1000:
            raise CoverageEvidenceUnavailable(
                "affected acceptance evidence exceeds bounded identity page"
            )

    bounded()
    for call in indexed_calls(connection, deployment, binding, record_ids=record_ids):
        if call["receipt"] is not None:
            receipt = CoverageModelUsageReceipt.model_validate(call["receipt"])
            if receipt.checkpoint_ref is None:
                raise ValueError("affected MODEL call has no checkpoint routing pointer")
            identifiers.add(_identity(receipt.checkpoint_ref))
            bounded()
    if not any(item.key.kind == "record_merge" for item in request.results):
        return tuple(sorted(identifiers))
    # Exact unit rows route prior part observations. Missing/corrupt routing rows
    # cannot grant acceptance: canonical batches/keys are reverified under locks.
    rows = connection.execute(
        """SELECT unit_key FROM coverage_units WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s AND unit_key->>'record_id'=ANY(%s)
           AND result IS NOT NULL ORDER BY ordinal LIMIT 1001""",
        (deployment, binding.namespace, binding.run_id, record_ids),
    ).fetchall()
    if len(rows) > 1000:
        raise CoverageEvidenceUnavailable("affected acceptance units exceed bounded routing page")
    identifiers.update(observation_id(binding, CoverageUnitKey.model_validate(row["unit_key"]))
                       for row in rows)
    bounded()
    # Same conservative routing as _ModelVerification.batches: absent/malformed
    # record_ids never silently remove a source. Legacy overflow refuses this
    # operation; the generic public acceptance retains its independent behavior.
    rows = connection.execute(
        """SELECT payload->'request'->>'result_artifact_ref' AS ref FROM session_events
           WHERE deployment_namespace=%s AND session_id=%s
             AND event_type='coverage_batch_accepted' AND payload->>'namespace'=%s
             AND payload->>'run_id'=%s AND (NOT payload ? 'record_ids'
               OR jsonb_typeof(payload->'record_ids') IS DISTINCT FROM 'array'
               OR (payload->'record_ids') ?| %s) ORDER BY sequence LIMIT 1001""",
        (deployment, binding.session_id, binding.namespace, binding.run_id, record_ids),
    ).fetchall()
    if len(rows) > 1000:
        raise CoverageEvidenceUnavailable("affected acceptance batches exceed bounded routing page")
    identifiers.update(_identity(row["ref"]) for row in rows)
    bounded()
    return tuple(sorted(identifiers))
