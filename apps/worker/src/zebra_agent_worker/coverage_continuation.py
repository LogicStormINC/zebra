"""Receipt-backed normal proof; shared recovery entry retains native authority gates.

This never permits MODEL HTTP or publication: their own admission/reservation and
independent certification remain mandatory. Legacy witnesses retain full recovery.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_storage.postgres.command_wakeup_recovery_proof import MAX_TOTAL_AGE
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.coverage_execution_receipt_read import read_execution_receipt
from agent_storage.postgres.coverage_recovery_preparation import (
    CoverageRecoveryDeferred,
    remaining_recovery_time,
)
from agent_storage.worker_capability_configuration import (
    NATIVE_CONTINUATION_VERIFIER as NATIVE_CONTINUATION_VERIFIER,
)


def continuation_has_budget(facts: Any, policy: Any, proof: Any) -> bool:
    """Unknown/insufficient predicate retains exact legacy remaining-part replay."""
    return facts is not None and facts.model_work_remaining is not None and (
        not facts.model_work_remaining or (
            proof is not None and facts.budget.calls < policy.max_calls
            and policy.max_tokens - facts.budget.charged_tokens >= proof.context_window
        )
    )


def continuation_facts(
    connection: Any, namespace: str, binding: Any, pending: Any, receipt: Any,
    policy: Any, run: Any,
) -> Any:
    facts = read_execution_receipt(connection, namespace, binding)
    if facts is None or facts.verifier_contract is None:
        return None
    if facts.verifier_contract != NATIVE_CONTINUATION_VERIFIER:
        raise ValueError("normal continuation verifier protocol is unsupported")
    row = connection.execute(
        """SELECT to_jsonb(p) AS pending,to_jsonb(r) AS receipt,w.body
           FROM session_command_pending p JOIN command_handoff_receipts r
             ON r.deployment_namespace=p.deployment_namespace
               AND r.accepted_event_id=p.accepted_event_id
           JOIN coverage_execution_receipts w ON w.deployment_namespace=p.deployment_namespace
             AND w.event_id=%s WHERE p.deployment_namespace=%s AND p.accepted_event_id=%s""",
        (facts.event.event_id, namespace, pending["accepted_event_id"]),
    ).fetchone()
    if row is None:
        raise ValueError("normal continuation has no exact native command")
    original = row["body"]["command"]
    if (
        original["receipt"] != row["receipt"]
        or any(original["pending"][k] != v for k, v in row["pending"].items()
               if k not in {"current_generation", "recovery_due_at", "recovery_code"})
        or facts.budget.policy != policy
        or run["source_watermark"] != facts.event.sequence
        or pending["current_generation"] not in {
            receipt["wake_generation"], receipt["wake_generation"] + 1,
        }
        or original["pending"]["current_generation"] != receipt["wake_generation"]
    ):
        raise ValueError("normal continuation receipt changed its producing command/policy")
    return facts


def finish_continuation_proof(
    *, connection: Any, namespace: str, binding: Any, pending: Any, receipt: Any,
    pinned: Any, run: Any, revision: int, events: Any, facts: Any,
    external: Any, gateway: Any, finalizers: list[Any] | None,
) -> dict[str, Any]:
    from agent_core.domain.coverage_contracts import coverage_digest

    if finalizers is None:
        raise ValueError("normal continuation requires prepared final authority")
    host = pinned.host_capability.host_context
    deadline = min(facts.valid_until, host.expires_at, pending["created_at"] + MAX_TOTAL_AGE)

    @postgres_connection_scope()
    def final_authority(limit: float) -> None:
        remaining_recovery_time(limit)
        with httpx.Client(
            verify=True, trust_env=False, follow_redirects=False,
            timeout=remaining_recovery_time(limit) / 4,
        ) as fresh:
            gateway.transport = HttpHostToolTransport(client=fresh, deadline_monotonic=limit)
            try:
                external()
            except CoverageRefusedError as error:
                if error.reason is CoverageRefusalReason.UPSTREAM_NOT_READY:
                    raise CoverageRecoveryDeferred("final Host proof unavailable") from None
                raise
            remaining_recovery_time(limit)

    finalizers.append(final_authority)
    external()
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    if not facts.budget.policy.started_at <= now < deadline or datetime.now(UTC) >= deadline:
        raise ValueError("normal continuation original authority expired")
    return {
        "session_id": str(binding.session_id),
        "accepted_event_id": str(pending["accepted_event_id"]),
        "generation": receipt["wake_generation"],
        "floor": receipt["execution_floor_sequence"],
        "stream_revision": revision,
        "receipt_digest": coverage_digest({
            k: v if v is None or isinstance(v, str | int) else str(v)
            for k, v in receipt.items()
        }),
        "run_id": binding.run_id, "namespace": binding.namespace,
        "task_binding_digest": pinned.binding_digest,
        "source_watermark": run["source_watermark"],
        "source_digest": coverage_digest([e.model_dump(mode="json") for e in events]),
        "expected_count": facts.expected_count, "expected_digest": facts.expected_digest,
        "accepted_count": facts.accepted_count, "valid_until": deadline.isoformat(),
        "continuation_protocol": "coverage-execution-receipt/1",
        "execution_receipt_digest": facts.receipt_digest,
        "execution_event_id": str(facts.event.event_id),
    }
