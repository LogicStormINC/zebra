"""Bounded native source facts; no Task mutation or latest-draft resolution."""

from typing import Any

from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.bundle_definition import BundleDefinitionVersion, snapshot_from_release
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from agent_core.domain.runtime_bundle_json import canonical_json_bytes, json_digest
from agent_core.domain.runtime_bundle_types import BundleScope
from agent_core.domain.runtime_gates import GateCandidate, GateWork
from psycopg.types.json import Jsonb

from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.work_unit import postgres_transaction_work_unit

MAX_TASKS = 32


def foreign_scope(c: Any, scope: BundleScope) -> bool:
    return (
        c.execute(
            """SELECT 1 FROM host_management_approvals
      WHERE deployment_namespace=%s AND
      (product_id,environment,deployment_id)<>(%s,%s,%s) LIMIT 1""",
            (scope.namespace_id, scope.product_id, scope.environment, scope.deployment_id),
        ).fetchone()
        is not None
        or c.execute(
            """
    SELECT 1 FROM agent_definition_bundle_versions WHERE namespace_id=%s AND
    snapshot#>'{runtime_assembly,bundle,manifest,scope}' IS DISTINCT FROM %s LIMIT 1
    """,
            (scope.namespace_id, Jsonb(scope.model_dump(mode="json"))),
        ).fetchone()
        is not None
    )


def blocker_facts(c: Any, namespace: str) -> dict[str, int]:
    facts = {}
    for name, sql in {
        "unreleased_leases": """
    SELECT 1 FROM worker_leases WHERE deployment_namespace=%s AND released_at IS NULL
    LIMIT 33
    """,
        "pending_commands": """
    SELECT 1 FROM session_command_pending WHERE deployment_namespace=%s AND
    status='pending' LIMIT 33
    """,
        "unsettled_effects": """
    SELECT 1 FROM effect_outbox WHERE deployment_namespace=%s AND status NOT IN
    ('succeeded','failed_no_effect') LIMIT 33
    """,
        "projection_lag": """
    SELECT 1 FROM session_streams s LEFT JOIN session_projections p
    USING(deployment_namespace,session_id) WHERE s.deployment_namespace=%s AND
    (p.session_id IS NULL OR s.current_version<>p.current_sequence) LIMIT 1
    """,
    }.items():
        facts[name] = len(c.execute(sql, (namespace,)).fetchall())
    facts["active_sessions"] = len(
        c.execute(
            """
    SELECT 1 FROM session_projections WHERE deployment_namespace=%s AND status NOT IN
    ('completed','failed','cancelled') LIMIT 33
    """,
            (namespace,),
        ).fetchall()
    )
    return facts


def candidate_snapshot(
    c: Any, registry: PostgresAgentRegistry, scope: BundleScope, pin: GateCandidate
) -> dict[str, Any]:
    key = AgentDefinitionScope(
        authority_issuer=scope.authority_issuer,
        namespace_id=scope.namespace_id,
        definition_id=AgentDefinitionId(pin.definition_id),
    )
    with postgres_transaction_work_unit(registry._database, c):
        release = registry.resolve_published(key, environment=scope.environment)
        version = registry.get_version(key, AgentDefinitionVersionId(pin.version_id))
    if (
        release is None
        or not isinstance(version, BundleDefinitionVersion)
        or (release.release_id, release.version_id, release.revision, release.definition_digest)
        != (pin.release_id, pin.version_id, pin.release_revision, pin.definition_digest)
        or version.runtime_assembly.bundle.bundle_digest != pin.bundle_digest
        or version.runtime_assembly.bundle.manifest.scope != scope
    ):
        raise ValueError("CANDIDATE_NOT_CURRENT")
    return snapshot_from_release(
        release=release, version=version, resolved_at=release.effective_at
    ).model_dump(mode="json")


def build_work(
    c: Any,
    registry: PostgresAgentRegistry,
    scope: BundleScope,
    operation: str,
    pin: GateCandidate,
    revision: int,
) -> GateWork:
    snapshot = candidate_snapshot(c, registry, scope, pin)
    facts = blocker_facts(c, scope.namespace_id)
    facts["scope_conflict"] = int(foreign_scope(c, scope))
    rows = c.execute(
        """
    SELECT p.session_id,p.status,p.current_sequence, (SELECT
    jsonb_build_object('definition_snapshot',e.payload->'definition_snapshot',
    'coverage',e.payload ?
    'coverage_admission','model_profile',e.payload->'model_profile',
    'reasoning_effort',e.payload->'reasoning_effort') FROM session_events e WHERE
    e.deployment_namespace=p.deployment_namespace AND e.session_id=p.session_id AND
    e.event_type='task_prepared' ORDER BY sequence DESC LIMIT 1) AS prepared, (SELECT
    jsonb_build_object('model_profile',e.payload->'model_profile','reasoning_effort',e.payload->'reasoning_effort')
    FROM session_events e WHERE e.deployment_namespace=p.deployment_namespace AND
    e.session_id=p.session_id AND e.event_type='user_message_received' ORDER BY sequence
    DESC LIMIT 1) AS user_policy FROM session_projections p WHERE
    p.deployment_namespace=%s AND p.status NOT IN ('completed','failed','cancelled')
    ORDER BY p.session_id LIMIT 33
    """,
        (scope.namespace_id,),
    ).fetchall()
    tasks = tuple({**row, "session_id": str(row["session_id"])} for row in rows)
    facts["overflow"] = int(len(tasks) > MAX_TASKS or len(canonical_json_bytes(tasks)) > 2_097_152)
    facts["unbound_tasks"] = sum(
        not isinstance(t["prepared"], dict)
        or not isinstance(t["prepared"].get("definition_snapshot"), dict)
        for t in tasks
    )
    # No raw Task bytes leave this adapter's Worker port or enter the public response.
    fingerprint = json_digest(
        {"gateRevision": revision, "candidate": snapshot, "tasks": tasks, "facts": facts}
    )
    return GateWork(operation, fingerprint, snapshot, tasks, facts)
