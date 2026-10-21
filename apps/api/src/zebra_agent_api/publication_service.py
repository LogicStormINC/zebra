"""Translate the approved publisher channel into existing native use cases."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.application.agent_definitions import AgentDefinitionDraftService
from agent_core.application.agent_publication import (
    AgentDefinitionPublicationService,
    PublicationGateEvidence,
)
from agent_core.domain.bundle_definition import BundleDefinitionVersion
from agent_core.domain.identifiers import AgentDefinitionVersionId
from agent_core.domain.runtime_bundle import parse_runtime_bundle
from agent_core.domain.runtime_bundle_json import canonical_json_bytes
from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from zebra_agent_config.bundle_settings import load_execution_catalog

from zebra_agent_api.publication_config import PublicationApproval


def mutate_publication(
    approval: PublicationApproval,
    payload: dict[str, Any],
    registry: PostgresAgentRegistry,
    catalog_path: str | None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    action = payload["action"]
    scope = approval.definition_scope
    version_id = AgentDefinitionVersionId(UUID(payload["versionId"]))
    if action == "materialize":
        if set(payload) != {
            "action",
            "operationId",
            "expectedRevision",
            "versionId",
            "version",
            "bundle",
        }:
            raise ValueError("INVALID_ARGUMENT")
        if type(payload["version"]) is not int or not 1 <= payload["version"] <= 2**53 - 1:
            raise ValueError("INVALID_ARGUMENT")
        bundle = parse_runtime_bundle(canonical_json_bytes(payload["bundle"]))
        if bundle.manifest.scope != approval.scope:
            raise PermissionError("SCOPE_MISMATCH")
        assembly = load_execution_catalog(catalog_path).resolve(bundle)
        service = AgentDefinitionDraftService(registry, approval.resolver())
        draft = registry.get_draft(scope)
        if draft is None:
            service.create_draft(
                definition_id=scope.definition_id,
                namespace_id=scope.namespace_id,
                actor_ref=approval.actor,
                updated_at=now,
                **approval.template,
            )
        else:
            service.update_draft(
                definition_id=scope.definition_id,
                namespace_id=scope.namespace_id,
                actor_ref=approval.actor,
                expected_revision=draft.revision,
                updated_at=now,
                **approval.template,
            )
        service.validate_draft(
            definition_id=scope.definition_id,
            namespace_id=scope.namespace_id,
            actor_ref=approval.actor,
            evaluated_at=now,
        )
        version = service.materialize_version(
            definition_id=scope.definition_id,
            namespace_id=scope.namespace_id,
            actor_ref=approval.actor,
            version_id=version_id,
            version=payload["version"],
            created_at=now,
            runtime_assembly=assembly,
        )
        return {
            "action": action,
            "definitionId": str(scope.definition_id),
            "versionId": str(version_id),
            "definitionDigest": version.definition_digest,
            "bundleDigest": bundle.bundle_digest,
            "assemblyDigest": assembly.assembly_digest,
        }
    if action != "publish" or set(payload) != {
        "action",
        "operationId",
        "expectedRevision",
        "versionId",
        "evidenceId",
    }:
        raise ValueError("INVALID_ARGUMENT")
    published_version = registry.get_version(scope, version_id)
    evidence = registry.latest_eval_evidence(scope, version_id)
    if (
        not isinstance(published_version, BundleDefinitionVersion)
        or published_version.runtime_assembly.bundle.manifest.scope != approval.scope
        or evidence is None
        or str(evidence.evidence_id) != payload["evidenceId"]
        or evidence.evaluator_actor not in approval.evaluator_actors
        or evidence.case_summary.get("policy_version") != approval.policy_version
        or evidence.definition_digest != published_version.definition_digest
        or not evidence.passed
        or "runtime-bundle/"
        + published_version.runtime_assembly.bundle.bundle_digest.removeprefix("sha256:")
        + "@1"
        not in approval.references
    ):
        raise PermissionError("PUBLICATION_GATE_REQUIRED")
    release = AgentDefinitionPublicationService(registry, approval.resolver()).publish(
        scope,
        version_id=version_id,
        environment=approval.scope.environment,
        actor_ref=approval.actor,
        gate=PublicationGateEvidence(
            version_id, evidence.definition_digest, True, approval.policy_version
        ),
        effective_at=now,
    )
    return {
        "action": action,
        "definitionId": str(scope.definition_id),
        "versionId": str(version_id),
        "definitionDigest": published_version.definition_digest,
        "bundleDigest": published_version.runtime_assembly.bundle.bundle_digest,
        "assemblyDigest": published_version.runtime_assembly.assembly_digest,
        "releaseId": str(release.release_id),
        "releaseRevision": release.revision,
        "evidenceId": str(evidence.evidence_id),
    }
