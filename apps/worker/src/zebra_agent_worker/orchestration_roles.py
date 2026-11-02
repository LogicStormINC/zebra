"""Resolve native published roles in the exact parent Registry scope."""

from datetime import UTC, datetime
from typing import Any, NoReturn

from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, BundleDefinitionVersion
from agent_core.domain.subagents import SubagentRole
from agent_orchestration.application.orchestration_port import OrchestrationToolError
from agent_storage.postgres.agent_registry import PostgresAgentRegistry


def refuse(detail: str) -> NoReturn:
    raise OrchestrationToolError("orchestration_forbidden", detail)


class PublishedOrchestrationRoles:
    def __init__(self, registry: PostgresAgentRegistry) -> None:
        self.registry = registry

    def current(
        self, connection: Any, snapshot: BundleDefinitionSnapshot, *, frozen: bool = False
    ) -> tuple[str, BundleDefinitionSnapshot]:
        # Native publication supersedes/revokes this row. A shared lock keeps
        # the checked release current through the enclosing admission commit.
        connection.execute(
            "SELECT definition_id FROM agent_definition_records WHERE authority_issuer=%s "
            "AND namespace_id=%s AND definition_id=%s FOR SHARE",
            snapshot.scope.scope_key,
        ).fetchone()
        definition = self.registry.get_definition(snapshot.scope)
        version = self.registry.get_version(snapshot.scope, snapshot.version_id)
        row = connection.execute(
            "SELECT environment,status,revision,version_id,definition_digest "
            "FROM agent_release_records WHERE authority_issuer=%s "
            "AND namespace_id=%s AND definition_id=%s AND release_id=%s FOR SHARE",
            (*snapshot.scope.scope_key, snapshot.release_id),
        ).fetchone()
        if definition is None or row is None or not isinstance(version, BundleDefinitionVersion):
            refuse("current published Bundle Definition is required")
        if (
            row["status"] == "revoked"
            or row["revision"] < snapshot.release_revision
            or str(row["version_id"]) != str(snapshot.version_id)
            or row["definition_digest"] != snapshot.definition_digest
            or version != snapshot.bound_version
        ):
            refuse("bound release was revoked or immutable Definition identity disagrees")
        if frozen:
            # Superseding a Release does not rebind existing Tasks. Their frozen
            # Version/assembly survives deprecation; explicit revocation does not.
            return definition.name, snapshot
        if row["status"] != "published" or row["revision"] != snapshot.release_revision:
            refuse("current published child role is required")
        identities = connection.execute(
            "SELECT d.definition_id FROM agent_definition_records d JOIN agent_release_records r "
            "USING(authority_issuer,namespace_id,definition_id) WHERE d.authority_issuer=%s "
            "AND d.namespace_id=%s AND d.name=%s AND r.environment=%s AND r.status='published'",
            (snapshot.authority_issuer, snapshot.namespace_id, definition.name, row["environment"]),
        ).fetchall()
        if len(identities) != 1:
            refuse("ambiguous current published Definition identity")
        release = self.registry.resolve_published(snapshot.scope, environment=row["environment"])
        if release is None:
            refuse("published role is absent")
        current = BundleDefinitionSnapshot.from_release(
            release=release, version=version, resolved_at=snapshot.resolved_at
        )
        if current != snapshot:
            refuse("published role moved or snapshot disagrees with Registry")
        return definition.name, current

    def roles(
        self, connection: Any, parent: BundleDefinitionSnapshot
    ) -> dict[str, BundleDefinitionSnapshot]:
        environment = parent.bound_version.runtime_assembly.bundle.manifest.scope.environment
        rows = connection.execute(
            "SELECT definition_id,name FROM agent_definition_records WHERE authority_issuer=%s "
            "AND namespace_id=%s AND name = ANY(%s)",
            (
                parent.authority_issuer,
                parent.namespace_id,
                [f"system/{role.value}" for role in SubagentRole],
            ),
        ).fetchall()
        result: dict[str, BundleDefinitionSnapshot] = {}
        for row in rows:
            role = row["name"].removeprefix("system/")
            scope = AgentDefinitionScope(
                authority_issuer=parent.authority_issuer,
                namespace_id=parent.namespace_id,
                definition_id=row["definition_id"],
            )
            release = self.registry.resolve_published(scope, environment=environment)
            if release is None:
                continue
            if role in result:
                refuse("ambiguous published role")
            version = self.registry.get_version(scope, release.version_id)
            if not isinstance(version, BundleDefinitionVersion):
                refuse("published role lacks native runtime assembly")
            result[role] = BundleDefinitionSnapshot.from_release(
                release=release, version=version, resolved_at=datetime.now(UTC)
            )
        return result
