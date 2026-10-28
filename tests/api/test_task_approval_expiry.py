"""Real PG approval handoff after human waiting outlives the original Host grant."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.task_bindings import host_context_digest
from agent_storage.postgres.task_admission import load_task_binding, save_task_binding
from zebra_agent_api import task_approval as mod
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_task_approval import body, dsn, postgres_dsn, seed
from tests.api.test_session_binding_renewal import _verified

__all__ = ["dsn", "postgres_dsn"]


def test_expired_approval_renews_before_original_run_wakeup(dsn, monkeypatch):
    db, tid, rid = seed(dsn)
    binding = load_task_binding(dsn, deployment_namespace=NAMESPACE, task_id=tid)
    now = datetime.now(UTC)
    before = now - timedelta(minutes=3)
    expired_context = binding.host_capability.host_context.model_copy(
        update={"expires_at": now - timedelta(minutes=1)}
    )
    expired = binding.model_copy(
        update={
            "binding_revision": binding.binding_revision + 1,
            "bound_at": before,
            "host_capability": binding.host_capability.model_copy(
                update={
                    "host_context": expired_context,
                    "bound_at": before,
                    "grant_expires_at": expired_context.expires_at,
                    "grant_digest": host_context_digest(expired_context),
                }
            ),
        }
    )
    save_task_binding(
        dsn,
        deployment_namespace=NAMESPACE,
        binding=expired,
        expected_previous_revision=binding.binding_revision,
    )
    resolver = BoundHostExecutionAuthorityResolver(expired)
    request = ExecutionAuthorityResolutionRequest(
        session_id=tid, attempt_number=1, scope=resolver.scope, validated_at=before
    )
    prior = resolver.resolve_for_attempt(request)
    fresh = expired_context.model_copy(
        update={"grant_id": "fresh-user-click", "expires_at": now + timedelta(minutes=5)}
    )
    grant = replace(_verified(fresh), authority_issuer=binding.host_capability.authority_issuer)
    app = SimpleNamespace(
        settings=SimpleNamespace(
            deployment="cloud", storage_authority="postgresql", database_url=dsn
        ),
        stores=SimpleNamespace(
            deployment_namespace=NAMESPACE, events=SimpleNamespace(_database=db)
        ),
    )
    monkeypatch.setattr(mod, "PostgresControlPlaneStores", SimpleNamespace)
    monkeypatch.setattr(mod, "task_access_response", lambda *a, **k: None)
    view = mod.task_approval(db, tid, rid)
    intent = body(view)
    intent.pop("operator")
    intent.pop("run_id")
    route = SimpleNamespace(
        method="POST", body=intent, query={}, host_context=fresh, verified_host_grant=grant
    )
    result = mod.handle_task_approval(app, route, str(tid), rid)
    assert result.status_code == 200 and result.body["decision"] == "approve"
    renewed = load_task_binding(dsn, deployment_namespace=NAMESPACE, task_id=tid)
    current = BoundHostExecutionAuthorityResolver(renewed)
    authority = current.resolve_renewed_binding(
        request.model_copy(update={"validated_at": datetime.now(UTC)}), prior
    )
    assert authority is not None and authority.expires_at > now
    assert authority.granted_authorities == prior.granted_authorities
    assert authority.effective_limits.is_no_broader_than(prior.effective_limits)
    assert renewed.agent_capability_ceiling == expired.agent_capability_ceiling
    with db.connect_task_io() as c:
        rows = c.execute(
            "SELECT event_type,count(*) AS n FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s GROUP BY event_type",
            (NAMESPACE, tid),
        ).fetchall()
    counts = {r["event_type"]: r["n"] for r in rows}
    assert counts["approval_granted"] == 1 and counts["session_command_accepted"] == 2
    assert counts.get("model_request_started", 0) == 0
