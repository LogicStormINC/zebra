"""Explicit cloud manifest bootstrap; does not dispatch an executor or Harness.

The source's create invoker must already be an admitted Effect. check_authority
must check current external revocation; persisted grants alone cannot do that.
"""

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.coverage_contracts import CoverageName, coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_snapshot import CoverageRecord, CoverageSnapshot
from agent_core.domain.coverage_task_admission import (
    CoverageTaskAdmission,
    coverage_admission_input,
)
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.coverage_snapshot_source import MAX_BYTES, HostCoverageSnapshotSource
from agent_integrations.coverage_snapshot_wire import Descriptor, verify_manifest
from agent_integrations.host_tools.contracts import HostToolManifest
from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.coverage_transactions import (
    assert_projection,
    binding_from_event,
    lock_run,
    manifest_event,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary
from agent_storage.postgres.task_index_transactions import _lock_task
from pydantic import TypeAdapter

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.task_recovery import apply_bound_host_context, recover_task


@dataclass(frozen=True)
class CloudCoverageBootstrap:
    binding: CoverageRunBinding
    records: tuple[CoverageRecord, ...]
    artifacts: CloudCoverageArtifacts
    store: PostgresCoverageStore
    sequence: int


def bootstrap_cloud_coverage(
    *,
    dsn: str,
    deployment_namespace: str,
    metadata: PostgresCloudArtifactPayloadStore,
    objects: ArtifactObjectStorePort,
    source: HostCoverageSnapshotSource,
    host_authority: HostContextEnvelope,
    admission: CoverageTaskAdmission,
    task_id: TaskId,
    session_id: SessionId,
    run_id: str,
    fence: LeaseFence,
    authority: Callable[[], WorkerMutationAuthority],
    check_authority: Callable[[], None],
    sync_events: Callable[[], None],
    snapshot_id: str | None = None,
) -> CloudCoverageBootstrap:
    """Prepare afresh, publish/read back an immutable manifest, then bind.

    Recovery supplies the existing snapshot ID. Create retries use a key derived
    from the admitted identity, never a new random key after an uncertain Effect.
    Callbacks are synchronous and must propagate STOP, lease loss and revocation.
    No credentials are read from environment or included in returned records.
    """
    database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
    if (
        metadata._database.deployment_namespace != deployment_namespace
        or metadata._database._dsn != dsn
    ):
        raise ValueError("coverage metadata must use the configured database and deployment")
    run_id = TypeAdapter(CoverageName).validate_python(run_id)
    host_authority = HostContextEnvelope.model_validate(coverage_admission_input(host_authority))
    admission = validate_coverage_admission(
        admission, host_context=host_authority, now=source.host.now()
    )
    if source.host.manifest is None or source.host.manifest.digest == "0" * 64:
        raise ValueError("coverage requires a real frozen Host manifest")
    manifest = HostToolManifest.from_payload(source.host.manifest.to_payload())
    if (
        source.session_id != session_id
        or source.host.bound != host_authority
        or source.host.resource != admission.source_resource
        or (source.host.contract is not None and source.host.contract != admission.contract)
        or (admission.contract.schema_version == 2 and source.host.contract is None)
    ):
        raise ValueError("coverage source does not bind the admitted Session and Host context")
    pinned_binding: str | None = None
    verified_revision: int | None = None
    events = PostgresEventStore(dsn, deployment_namespace=deployment_namespace)
    reader = CloudArtifactPayloadReader(
        metadata, objects, deployment_namespace=deployment_namespace
    )

    def fresh_authority() -> WorkerMutationAuthority:
        check_authority()
        raw = authority()
        for value, schema in (
            (raw, WorkerMutationAuthority),
            (raw.lease_fence, LeaseFence),
            (fence, LeaseFence),
        ):
            if value.__pydantic_extra__ or value.__dict__.keys() - schema.model_fields.keys():
                raise ValueError("coverage mutation authority carries unknown attributes")
        current = WorkerMutationAuthority.model_validate(
            {
                **raw.__dict__,
                "lease_fence": dict(raw.lease_fence.__dict__),
            }
        )
        LeaseFence.model_validate(dict(fence.__dict__))
        if (
            current.deployment_namespace != deployment_namespace
            or current.session_id != session_id
            or current.lease_fence != fence
        ):
            raise ValueError("coverage mutation authority changed Session, deployment or fence")
        return current

    def preflight() -> datetime:
        nonlocal pinned_binding, verified_revision
        current = fresh_authority()
        now = source.host.now()
        validate_coverage_admission(admission, host_context=host_authority, now=now)
        source.host.authority_check(host_authority)
        # Read/recover before taking locks: no Event-store second connection or
        # attachment I/O inside the transaction. Reject a raced append below.
        history = events.list_for_session(session_id)
        task = recover_task(
            history,
            workspace=rebuild_workspace(history),
            fallback_title="coverage",
            attachment_reader=reader,
        )
        # No provisional snapshot, unbound facade or run is needed for these checks.
        with database.connect() as connection:
            lock_session_lease_boundary(connection, deployment_namespace, session_id)
            assert_current_lease_fence(connection, deployment_namespace, session_id, fence)
            _lock_task(connection, deployment_namespace, task_id)
            row = connection.execute(
                """SELECT task.active_segment_id, binding.snapshot_json, binding.binding_digest,
                   session.namespace_id, stream.current_version
                   FROM agent_tasks task JOIN execution_segments segment
                     ON segment.deployment_namespace=task.deployment_namespace
                     AND segment.task_id=task.task_id AND segment.session_id=%s
                   JOIN session_projections session
                     ON session.deployment_namespace=segment.deployment_namespace
                     AND session.session_id=segment.session_id
                   JOIN session_streams stream
                     ON stream.deployment_namespace=session.deployment_namespace
                     AND stream.session_id=session.session_id
                   JOIN LATERAL (SELECT snapshot_json, binding_digest FROM task_binding_snapshots
                     WHERE deployment_namespace=task.deployment_namespace AND task_id=task.task_id
                     ORDER BY binding_revision DESC LIMIT 1) binding ON TRUE
                   WHERE task.deployment_namespace=%s AND task.task_id=%s
                   FOR UPDATE OF task, stream""",
                (session_id, deployment_namespace, task_id),
            ).fetchone()
            if row is None or row["active_segment_id"] != session_id:
                raise ValueError("coverage requires the current persisted Task segment")
            bound = TaskBindingSnapshot.model_validate(row["snapshot_json"])
            host = bound.host_capability
            if source.host.manifest != manifest or host.manifest_digest != manifest.digest:
                raise ValueError("coverage source manifest disagrees with persisted Task manifest")
            if (
                bound.task_id != str(task_id)
                or bound.binding_digest != row["binding_digest"]
                or host.host_context != host_authority
                or host.grant_digest != host_context_digest(host_authority)
                or host.host_app_id != host_authority.host_app_id
                or host.namespace_id != host_authority.namespace_id
                or row["namespace_id"] != host_authority.namespace_id
                or host.grant_expires_at is None
                or host.grant_expires_at <= now
                or host.bound_at > now
                or bound.bound_at > now
                or (pinned_binding is not None and pinned_binding != bound.binding_digest)
                or current.expected_stream_revision != row["current_version"]
                or not history
                or history[-1].sequence != row["current_version"]
            ):
                raise ValueError(
                    "coverage persisted Host/Task binding or mutation revision conflicts"
                )
            task = apply_bound_host_context(task, bound)
            if task.coverage_admission != admission or task.host_context != host_authority:
                raise ValueError("coverage admission disagrees with persisted Task identity")
            stopped = connection.execute(
                """SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
                   AND (event_type IN ('session_cancelled','session_failed','session_completed')
                     OR (event_type='session_command_accepted'
                         AND payload->>'kind' IN ('stop','cancel')))
                   LIMIT 1""",
                (deployment_namespace, session_id),
            ).fetchone()
            previous = manifest_event(
                connection, deployment_namespace, host_authority.namespace_id, run_id
            )
            if stopped is not None:
                raise ValueError("coverage Session is terminal or has accepted STOP/cancel")
            if previous is not None:
                old = binding_from_event(previous, host_authority.namespace_id, run_id)
                run = connection.execute(
                    """SELECT * FROM coverage_runs WHERE deployment_namespace=%s
                       AND namespace=%s AND run_id=%s""",
                    (deployment_namespace, host_authority.namespace_id, run_id),
                ).fetchone()
                if (
                    old.session_id != session_id
                    or old.task_id != task_id
                    or old.contract != admission.contract
                    or (snapshot_id is not None and old.snapshot.snapshot_id != snapshot_id)
                    or run is None
                    or run["cancelled"]
                ):
                    raise ValueError("coverage recovery identity conflicts or run is cancelled")
                assert_projection(connection, deployment_namespace, old, run)
            pinned_binding = bound.binding_digest
            verified_revision = int(row["current_version"])
        fresh_authority()
        return now

    sync_events()
    preflight()
    key = "coverage-snapshot:" + coverage_digest(
        {
            "deployment": deployment_namespace,
            "task": str(task_id),
            "session": str(session_id),
            "run": run_id,
            "host": host_context_digest(host_authority),
            "admission": admission.model_dump(mode="json"),
        }
    )
    prepared = (
        source.create(admission.contract, authority=host_authority, idempotency_key=key)
        if snapshot_id is None
        else source.get(snapshot_id, authority=host_authority)
    )
    # An admitted Effect can append Events before returning its descriptor.
    sync_events()
    preflight()
    descriptor = Descriptor.model_validate(coverage_admission_input(prepared.descriptor))
    records = TypeAdapter(tuple[CoverageRecord, ...]).validate_python(
        coverage_admission_input(prepared.records)
    )
    verify_manifest(descriptor, records)
    identifier = source.manifest_artifact_id(descriptor)
    if (
        prepared.manifest_artifact_id != identifier
        or descriptor.host_id != host_authority.host_app_id
        or descriptor.namespace != host_authority.namespace_id
        or (snapshot_id is not None and descriptor.snapshot_id != snapshot_id)
    ):
        raise ValueError("coverage source intent identity conflicts")
    maximum = min(MAX_BYTES, host_authority.limits.max_artifact_bytes)
    if len(prepared.manifest_bytes) > maximum:
        raise ValueError("coverage manifest exceeds the read bound")
    binding = CoverageRunBinding(
        namespace=host_authority.namespace_id,
        session_id=session_id,
        task_id=task_id,
        run_id=run_id,
        contract=admission.contract,
        snapshot=CoverageSnapshot(
            **descriptor.model_dump(),
            manifest_artifact_ref=f"artifact://{identifier}",
            source_resource_ref=source.host.resource.resource_id,
        ),
        manifest_artifact_digest=sha256(prepared.manifest_bytes).hexdigest(),
    )
    if binding.verify_manifest(prepared.manifest_bytes) != records:
        raise ValueError("coverage source manifest rows disagree with canonical bytes")

    def validate() -> datetime:
        now = preflight()
        source._live(descriptor)
        with database.connect() as connection:
            run, _ = lock_run(connection, deployment_namespace, binding, fence)
            if run is not None:
                assert_projection(connection, deployment_namespace, binding, run)
                if run["cancelled"]:
                    raise ValueError("coverage run is cancelled")
        return now

    validate()

    def live_check() -> None:
        # Publisher invokes this while holding its transaction locks. Do not
        # acquire those locks through another connection from the callback.
        fresh_authority()
        source.host.authority_check(host_authority)
        source._live(descriptor)
        if source.host.manifest != manifest:
            raise ValueError("coverage frozen Host manifest changed during publication")
        with database.connect() as connection:
            current = connection.execute(
                """SELECT binding_digest FROM task_binding_snapshots
                   WHERE deployment_namespace=%s AND task_id=%s
                   ORDER BY binding_revision DESC LIMIT 1""",
                (deployment_namespace, task_id),
            ).fetchone()
            if current is None or current["binding_digest"] != pinned_binding:
                raise ValueError("coverage persisted Task authority changed during publication")

    publisher = PostgresCoverageArtifactPublisher(
        dsn,
        deployment_namespace=deployment_namespace,
        metadata=metadata,
        objects=objects,
    )
    artifacts = CloudCoverageArtifacts(
        binding=binding,
        deployment_namespace=deployment_namespace,
        metadata=metadata,
        objects=objects,
        publisher=publisher,
        authority=fresh_authority,
        check_authority=live_check,
        sync_events=sync_events,
    )
    publication = CoverageArtifacts(artifacts, session_id, nullcontext())
    uri = publication.publish(
        identifier,
        "coverage_manifest",
        prepared.manifest_bytes,
        maximum,
        validate,
        descriptor.expires_at,
    )
    readback = publication.manifest(identifier, descriptor, maximum, validate())
    if readback != (binding.snapshot.manifest_artifact_ref, records) or uri != readback[0]:
        raise ValueError("coverage finalized manifest readback conflicts")
    store = PostgresCoverageStore(
        dsn,
        deployment_namespace=deployment_namespace,
        artifacts=artifacts,
    )
    validate()
    current = fresh_authority()
    if current.expected_stream_revision != verified_revision:
        raise ValueError("coverage mutation revision changed after strict identity verification")
    sequence = store.bind(
        binding,
        fence=current.lease_fence,
        expected_stream_revision=current.expected_stream_revision,
        task_binding_digest=pinned_binding,
    )
    sync_events()
    validate()
    return CloudCoverageBootstrap(binding, records, artifacts, store, sequence)
