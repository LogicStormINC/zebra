"""Compose current signed Host reads with the original certified report gate."""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, cast
from uuid import UUID

import httpx
from agent_core.contracts.task_prepared import TaskPreparedPayload
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageCertificate
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.tools import ToolCall, ToolResult
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.coverage_model_policy import REVIEWER_PROFILE
from agent_integrations.coverage_snapshot_invocation import HISTORY_RESOURCE_TYPE
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.coverage_snapshot_wire import Descriptor
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools import HostToolGateway, HostToolManifest, HostWorkloadIdentity
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import PostgresCloudArtifactPayloadStore, S3ArtifactObjectStore
from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from agent_storage.coverage_artifact_reader import CloudCoverageArtifactReader
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_recovery_preparation import remaining_recovery_time
from agent_storage.postgres.coverage_transactions import binding_from_event
from agent_storage.postgres.database import (
    PostgresDatabase,
    postgres_deadline,
)
from agent_storage.postgres.host_manifest_freeze import load_frozen_manifest_by_digest

from zebra_agent_api.coverage_report_authority import current_report_profile, validate_report_grant

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi

REPORT_READ_SECONDS = 20


def _composition(api: ZebraAgentApi) -> tuple[str, str, CloudArtifactPayloadReader]:
    settings, stores = api.settings, api.stores
    reader = getattr(stores, "artifact_payload_reader", None)
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or type(reader) is not CloudArtifactPayloadReader
        or type(reader._metadata) is not PostgresCloudArtifactPayloadStore
        or type(reader._objects) is not S3ArtifactObjectStore
        or not callable(getattr(reader._objects, "_deadline_client_factory", None))
        or reader._namespace != getattr(stores, "deployment_namespace", None)
        or reader._metadata is not cast(object, stores.artifact_payloads)
        or reader._metadata._database._dsn != settings.database_url
        or reader._metadata._database.deployment_namespace != reader._namespace
    ):
        raise RuntimeError("certified Cloud report storage unavailable")
    return settings.database_url, reader._namespace, reader


def _run(database: PostgresDatabase, task: TaskId) -> tuple[CoverageRunBinding, str] | None:
    with database.connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        root = connection.execute(
            "SELECT root_session_id FROM agent_tasks WHERE deployment_namespace=%s AND task_id=%s",
            (database.deployment_namespace, task),
        ).fetchone()
        if root is None:
            return None
        rows = connection.execute(
            "SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
            "AND event_type='coverage_manifest_committed' ORDER BY sequence LIMIT 2",
            (database.deployment_namespace, root["root_session_id"]),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("report Task has ambiguous coverage identity")
        row = rows[0]
        binding = binding_from_event(row, row["payload"]["namespace"], row["payload"]["run_id"])
        if binding.task_id != task or binding.session_id != SessionId(root["root_session_id"]):
            raise ValueError("report coverage identity conflicts with Task root")
        policy = task_policy(connection, database.deployment_namespace, binding)
        origin = connection.execute(
            "SELECT payload FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
            "AND event_type='task_prepared' ORDER BY sequence LIMIT 1",
            (database.deployment_namespace, binding.session_id),
        ).fetchone()
        if policy is None or origin is None:
            raise ValueError("report requires persisted strict Task admission")
        prepared = TaskPreparedPayload.model_validate(origin["payload"])
        if (
            prepared.coverage_admission is None
            or prepared.coverage_admission.contract != binding.contract
        ):
            raise ValueError("report conflicts with strict Task contract")
        return binding, prepared.coverage_admission.history_ref


def read_coverage_report(
    api: ZebraAgentApi,
    task_id: str,
    grant: VerifiedHostGrant,
) -> tuple[CoverageCertificate, str, bytes] | None:
    """Return only already certified, original canonical bytes under fresh authority."""
    with postgres_deadline(monotonic() + REPORT_READ_SECONDS) as deadline:
        result = _read_coverage_report(api, task_id, grant, deadline)
        remaining_recovery_time(deadline)
        return result


def _read_coverage_report(
    api: ZebraAgentApi, task_id: str, grant: VerifiedHostGrant, deadline: float,
) -> tuple[CoverageCertificate, str, bytes] | None:
    if type(grant) is not VerifiedHostGrant:
        raise PermissionError("verified report authority required")
    task = TaskId(UUID(task_id))
    dsn, deployment, reader = _composition(api)
    control = api.cloud_control
    if (
        control is None
        or control.deployment_namespace != deployment
        or control._database._dsn != dsn
    ):
        raise RuntimeError("report Task authority reader unavailable")
    frozen = control.load_task_binding(task)
    if frozen is None:
        raise PermissionError("report Task authority unavailable")
    # Check owner before loading strict source metadata; no old grant expiry check.
    histories = (
        [
            r.resource_id
            for r in frozen.host_capability.host_context.resource_refs
            if r.resource_type == HISTORY_RESOURCE_TYPE
        ]
        if frozen.host_capability.host_context
        else []
    )
    if len(histories) != 1:
        raise PermissionError("report Task has no exact history binding")
    validate_report_grant(frozen, grant, history_ref=histories[0])
    run = _run(PostgresDatabase(dsn, deployment_namespace=deployment), task)
    if run is None:
        return None
    binding, history_ref = run
    if (
        binding.namespace != grant.context.namespace_id
        or binding.snapshot.host_id != grant.context.host_app_id
    ):
        raise PermissionError("report snapshot authority conflicts")

    def local_check() -> None:
        remaining_recovery_time(deadline)
        current_report_profile(
            api, task, frozen, grant, history_ref=history_ref, dsn=dsn, deployment=deployment
        )

    profile = current_report_profile(
        api, task, frozen, grant, history_ref=history_ref, dsn=dsn, deployment=deployment
    )
    raw = load_frozen_manifest_by_digest(
        dsn,
        deployment_namespace=deployment,
        manifest_digest=frozen.host_capability.manifest_digest,
    )
    if raw is None:
        raise RuntimeError("report frozen Host manifest unavailable")
    manifest = HostToolManifest.from_payload(raw)
    if (
        manifest.digest != frozen.host_capability.manifest_digest
        or manifest.workload_identity != profile.workload_identity_ref
    ):
        raise PermissionError("report frozen Host manifest conflicts")
    secret = api.settings.host_tool_shared_secret
    if not secret:
        raise RuntimeError("report Host workload credential unavailable")
    credential = ConfiguredHmacHostCredentialResolver(secret).issue(
        credential_ref=profile.credential_ref,
        workload_identity_ref=profile.workload_identity_ref,
        audience=profile.base_uri,
        scopes=grant.context.scopes,
        ttl_seconds=60,
    )
    with httpx.Client(
        verify=HttpHostToolTransport._ssl_verify(), trust_env=False, follow_redirects=False
    ) as client:
        gateway = HostToolGateway(
            profile.base_uri,
            HostWorkloadIdentity(
                profile.workload_identity_ref, grant.context.namespace_id, grant.context.host_app_id
            ),
            shared_secret=credential.token,
            manifest=manifest,
            reconcile_path=profile.reconcile_path_template,
            transport=HttpHostToolTransport(client=client, deadline_monotonic=deadline),
        )

        def invoke(
            tool_call: ToolCall,
            context: HostContextEnvelope,
            *,
            idempotency_key: str | None = None,
            required_resource: HostResourceRef | None = None,
            manifest: HostToolManifest | None = None,
        ) -> ToolResult:
            result = gateway.invoke(
                tool_call,
                context,
                idempotency_key=idempotency_key,
                required_resource=required_resource,
                manifest=manifest,
            )
            if result.metadata.get("http_status") in (401, 403):
                raise PermissionError("current Host denied report source access")
            if result.metadata.get("reason") in (
                "timeout", "transport_error", "host_transport_error",
            ):
                raise RuntimeError("current Host report transport unavailable")
            return result

        source = HostCoverageSnapshotSource(
            session_id=binding.session_id,
            authority=grant.context,
            history_ref=history_ref,
            manifest=manifest,
            invoke=invoke,
            max_calls=8,
            max_seconds=remaining_recovery_time(deadline),
        )
        expected = Descriptor.model_validate(
            binding.snapshot.model_dump(exclude={"manifest_artifact_ref", "source_resource_ref"}),
        )
        def check() -> None:
            local_check()
            descriptor = source._get_descriptor(binding.snapshot.snapshot_id, grant.context, budget)
            source.host.publication_time(
                grant.context,
                budget,
                descriptor.as_of,
                descriptor.expires_at,
            )
            if descriptor != expected:
                raise PermissionError("report snapshot changed or authorization was revoked")
            local_check()

        try:
            budget = source.host.budget(grant.context)
            check()
            artifacts = CloudCoverageArtifactReader(
                reader._metadata,
                reader._objects,
                deployment_namespace=deployment,
                session_id=binding.session_id,
                deadline_monotonic=deadline,
            )
            store = PostgresCoverageStore(
                dsn,
                deployment_namespace=deployment,
                artifacts=artifacts,
                supported_model_profiles=(REVIEWER_PROFILE,),
                model_observation_deriver=derive_semantic_observation,
            )
            return store.certified_report(
                binding.namespace,
                binding.run_id,
                now=datetime.now(UTC),
                check_authority=check,
                authority_expires_at=grant.context.expires_at,
            )
        except CoverageRefusedError as exc:
            remaining_recovery_time(deadline)
            if exc.reason in (
                CoverageRefusalReason.AUTHORITY_INVALID,
                CoverageRefusalReason.SCOPE_MISMATCH,
            ):
                raise PermissionError("report authority was rejected") from exc
            raise ValueError("report source or retained certification was refused") from exc
