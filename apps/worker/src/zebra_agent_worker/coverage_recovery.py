"""Bounded native command recovery proof; never authorizes another model transport."""

import json
import os
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any, cast

import httpx
from agent_core.application.coverage_executor import MAX_UNITS
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.leases import LeaseFence
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.coverage_model_policy import REVIEWER_PROFILE
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.coverage_snapshot_wire import Descriptor
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_storage import S3ArtifactObjectStore
from agent_storage.postgres.command_wakeup_recovery import MAX_TOTAL_AGE
from agent_storage.postgres.connection_scope import postgres_connection_scope
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES, read_manifest
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_model_acceptance import pin_evidence
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_projection import replay_request
from agent_storage.postgres.coverage_transactions import (
    assert_projection,
    binding_from_event,
    lock_run,
    validate_event_fence,
)

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_certified import read_issued_report
from zebra_agent_worker.coverage_composition import CloudCoverageRuntime, load_official_model_policy
from zebra_agent_worker.coverage_recovery_authority import prepare_recovery_authority
from zebra_agent_worker.coverage_staged_recovery import (
    prove_uploaded_responses,
    revalidate_uploaded_responses,
    uploaded_responses_digest,
)
from zebra_agent_worker.host_gateway_resolution import (
    frozen_or_discovered_manifest,
    resolve_pinned_gateway,
)
from zebra_agent_worker.provider_configuration import model_provider_settings


def verify_cloud_coverage_recovery(
    runtime: CloudCoverageRuntime,
    service: Any,
    connection: Any,
    namespace: str,
    pending: dict[str, Any],
    receipt: dict[str, Any],
    *,
    finalizers: list[Callable[[float], None]] | None = None,
    continuation: bool = False,
    execution_authority: PostgresCoverageAuthority | None = None,
) -> dict[str, Any]:
    """Current authority plus original bytes and exact accepted Event/index equality."""
    session_id = pending["session_id"]
    if (
        namespace != runtime.deployment_namespace
        or runtime.metadata._database._dsn != runtime.dsn
        or runtime.metadata._database.deployment_namespace != namespace
    ):
        raise ValueError("strict command proof must use co-located native metadata")
    history = connection.execute(
        """SELECT * FROM (WITH bounds AS MATERIALIZED (
             SELECT count(*) AS history_count,
               coalesce(sum(octet_length(to_jsonb(e)::text)),0) AS history_bytes
             FROM session_events e WHERE deployment_namespace=%s AND session_id=%s)
           SELECT b.*,e.* FROM bounds b LEFT JOIN LATERAL (
             SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND b.history_count<=4096 AND b.history_bytes<=%s
             ORDER BY sequence LIMIT 4097) e ON TRUE) proof ORDER BY proof.sequence""",
        (namespace, session_id, namespace, session_id, MAX_COVERAGE_ARTIFACT_BYTES),
    ).fetchall()
    volume = history[0]
    if volume["history_count"] > 4096 or volume["history_bytes"] > MAX_COVERAGE_ARTIFACT_BYTES:
        raise ValueError("strict command proof exceeds bounded Session history")
    rows = [{k: v for k, v in r.items() if k not in {"history_count", "history_bytes"}}
            for r in history if r["event_id"] is not None]
    manifests = [r for r in rows if r["event_type"] == "coverage_manifest_committed"]
    if len(manifests) != 1:
        raise ValueError("strict command proof requires one canonical manifest")
    original = manifests[0]
    binding = binding_from_event(
        original, original["payload"]["namespace"], original["payload"]["run_id"]
    )
    run, revision = lock_run(connection, namespace, binding, None)
    assert_projection(connection, namespace, binding, run)
    task_row = connection.execute(
        """SELECT t.active_segment_id,b.snapshot_json,b.binding_digest,s.namespace_id
           FROM agent_tasks t JOIN LATERAL (
             SELECT snapshot_json,binding_digest FROM task_binding_snapshots
             WHERE deployment_namespace=t.deployment_namespace AND task_id=t.task_id
             ORDER BY binding_revision DESC LIMIT 1) b ON TRUE
           JOIN session_projections s ON s.deployment_namespace=t.deployment_namespace
             AND s.session_id=%s WHERE t.deployment_namespace=%s AND t.task_id=%s""",
        (session_id, namespace, binding.task_id),
    ).fetchone()
    if task_row is None or task_row["active_segment_id"] != session_id or run["cancelled"]:
        raise ValueError("strict command proof lost the active Task segment")
    pinned = TaskBindingSnapshot.model_validate_json(
        json.dumps(task_row["snapshot_json"]), strict=True
    )
    host = pinned.host_capability.host_context
    policy = task_policy(connection, namespace, binding)
    if (
        host is None
        or policy is None
        or policy.model_profile != REVIEWER_PROFILE
        or task_row["binding_digest"] != pinned.binding_digest
        or policy.task_binding_digest != pinned.binding_digest
        or task_row["namespace_id"] != host.namespace_id
        or original["payload"]["task_binding_digest"] != pinned.binding_digest
        or original["payload"]["task_binding_revision"] != pinned.binding_revision
        or binding.contract.checks != (semantic_check(REVIEWER_PROFILE).contract_check,)
    ):
        raise ValueError("strict command proof lost its admitted frozen authority")
    expires_at = host.expires_at
    resource_id = binding.snapshot.source_resource_ref
    if expires_at is None or resource_id is None:
        raise ValueError("strict command proof requires retained source authority")
    events = tuple(SessionEvent.model_validate(r) for r in rows)
    issued = tuple(e for e in events if e.event_type is EventType.COVERAGE_REPORT_CERTIFIED)
    if len(issued) > 1 or (
        issued and not policy.started_at <= issued[0].created_at < policy.deadline
    ):
        raise ValueError("strict recovery has no unique lawfully issued report")
    if any(
        e.event_type
        in {
            EventType.SESSION_CANCELLED,
            EventType.SESSION_FAILED,
            EventType.SESSION_COMPLETED,
            EventType.SESSION_SUSPENDED,
            EventType.TURN_COMPLETED,
            EventType.TURN_FAILED,
            EventType.TURN_CANCELLED,
        }
        or (
            e.event_type is EventType.SESSION_COMMAND_ACCEPTED
            and e.payload.get("kind") in {"stop", "cancel"}
        )
        for e in events
    ):
        raise ValueError("strict command proof has a stopped or closed execution")
    fence = LeaseFence(
        control_plane_epoch=receipt["control_plane_epoch"],
        fencing_token=receipt["fencing_token"],
        owner_instance_id=receipt["owner_instance_id"],
    )
    effect_rows = connection.execute(
        "SELECT * FROM effect_outbox WHERE deployment_namespace=%s "
        "AND execution_session_id=%s LIMIT 2",
        (namespace, session_id),
    ).fetchall()
    if len(effect_rows) > 1 or any(r["status"] != "succeeded" for r in effect_rows):
        raise ValueError("strict command proof has an unresolved native Effect")
    effect_events = {
        value
        for r in effect_rows
        for value in (r["intent_event_id"], r["terminal_event_id"])
        if value is not None
    }
    for event in events:
        if event.sequence <= receipt["execution_floor_sequence"]:
            continue
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED:
            if event.event_id != receipt["started_event_id"]:
                raise ValueError("strict command proof has another started execution")
        elif event.event_type in {
            EventType.TOOL_EXECUTION_STARTED,
            EventType.TOOL_EXECUTION_COMPLETED,
        }:
            if (
                event.event_id not in effect_events
                or event.payload.get("tool_name") != "dataset.snapshot.create"
            ):
                raise ValueError("strict command proof has an unrelated tool execution")
        elif event.event_type.value.startswith("coverage_") and event.event_type not in {
            EventType.COVERAGE_RUN_CANCELLED,
        }:
            validate_event_fence(event.payload)
            if event.payload["fence"] != fence.model_dump(mode="json"):
                raise ValueError("strict command proof tail belongs to another lease")
        else:
            raise ValueError("strict command proof has uncertain post-floor Events")

    current = prepare_recovery_authority(
        runtime, service, session_id, pinned, fence, policy, issued=bool(issued),
        execution_authority=execution_authority if continuation else None,
    )

    def readonly_authority() -> Any:
        raise ValueError("command recovery proof cannot publish Artifacts")

    with ExitStack() as cleanup:
        current()
        gateway = resolve_pinned_gateway(
            host,
            service._egress_registry,
            ConfiguredHmacHostCredentialResolver(service._settings.host_tool_shared_secret),
        )
        if gateway is None:
            raise ValueError("strict command proof requires current pinned Host egress")
        manifest = frozen_or_discovered_manifest(
            gateway, host, pinned.host_capability.manifest_digest, service._frozen_manifest_loader
        )
        client = cleanup.enter_context(
            httpx.Client(verify=True, trust_env=False, follow_redirects=False)
        )
        gateway.transport = HttpHostToolTransport(client=client)
        source = HostCoverageSnapshotSource(
            session_id=session_id, authority=host, contract=binding.contract,
            source_ref=HostResourceRef(
                type=binding.contract.source_definition.resource_type, id=resource_id),
            manifest=manifest, invoke=gateway.invoke,
        )

        def external() -> None:
            current()
            latest = resolve_pinned_gateway(
                host,
                service._egress_registry,
                ConfiguredHmacHostCredentialResolver(service._settings.host_tool_shared_secret),
            )
            if latest is None or (
                latest.endpoint,
                latest.workload_identity,
                latest.shared_secret,
            ) != (gateway.endpoint, gateway.workload_identity, gateway.shared_secret):
                raise ValueError("strict command proof Host connector changed")
            descriptor = source._get_descriptor(
                binding.snapshot.snapshot_id, host, source.host.budget(host)
            )
            frozen = Descriptor.model_validate(
                binding.snapshot.model_dump(
                    exclude={"manifest_artifact_ref", "source_resource_ref"}
                )
            )
            if descriptor != frozen:
                raise ValueError("strict command proof external snapshot changed")

        external()
        provider = model_provider_settings(service._settings).api_key_env
        proof = (
            None if issued else load_official_model_policy(
                api_key=os.environ.get(provider, ""), deadline=policy.deadline,
                check_authority=external,
            )
        )
        if continuation and not issued:
            from zebra_agent_worker.coverage_continuation import (
                continuation_facts,
                continuation_has_budget,
                finish_continuation_proof,
            )

            facts = continuation_facts(
                connection, namespace, binding, pending, receipt, policy, run,
            )
            if continuation_has_budget(facts, policy, proof):
                return finish_continuation_proof(
                    connection=connection, namespace=namespace, binding=binding, pending=pending,
                    receipt=receipt, pinned=pinned, run=run, revision=revision, events=events,
                    facts=facts, external=external, gateway=gateway, finalizers=finalizers,
                )
        artifacts: Any = CloudCoverageArtifacts(
            binding=binding,
            deployment_namespace=namespace,
            metadata=runtime.metadata,
            objects=runtime.objects,
            publisher=PostgresCoverageArtifactPublisher(
                runtime.dsn,
                deployment_namespace=namespace,
                metadata=runtime.metadata,
                objects=runtime.objects,
            ),
            authority=readonly_authority,
            check_authority=external,
            sync_events=lambda: None,
        )
        originals: dict[str, tuple[Any, bytes]] = {}
        if finalizers is not None:
            from zebra_agent_worker.coverage_recovery_preparation import RecoveryArtifactReads

            artifacts = RecoveryArtifactReads(artifacts, connection, originals)
        deadlines = [
            min(binding.snapshot.expires_at, expires_at, pending["created_at"] + MAX_TOTAL_AGE)
        ]
        if not issued:
            deadlines[0] = min(deadlines[0], policy.deadline)
        pin_evidence(
            connection,
            namespace,
            binding,
            artifacts,
            binding.snapshot.manifest_artifact_ref,
            binding.manifest_artifact_digest,
            deadlines,
        )
        records = read_manifest(artifacts, binding)
        keys = expected_units(binding.contract, records, max_units=MAX_UNITS)
        expected = {
            coverage_digest(k.model_dump(mode="json")): k.model_dump(mode="json") for k in keys
        }
        unit_rows = connection.execute(
            """SELECT * FROM (WITH bounds AS MATERIALIZED (
                 SELECT count(*) AS unit_count,
                   coalesce(sum(octet_length(to_jsonb(u)::text)),0) AS unit_bytes
                 FROM coverage_units u
                 WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s)
               SELECT b.*,u.* FROM bounds b LEFT JOIN LATERAL (
                 SELECT unit_digest,unit_key,result,ordinal FROM coverage_units
                 WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
                   AND b.unit_count=%s AND b.unit_bytes<=%s
                 ORDER BY ordinal LIMIT %s) u ON TRUE) proof ORDER BY proof.ordinal""",
            (namespace, binding.namespace, binding.run_id,
             namespace, binding.namespace, binding.run_id,
             len(keys), MAX_COVERAGE_ARTIFACT_BYTES, len(keys) + 1),
        ).fetchall()
        unit_volume = unit_rows[0]
        if (unit_volume["unit_count"] != len(keys)
                or unit_volume["unit_bytes"] > MAX_COVERAGE_ARTIFACT_BYTES):
            raise ValueError("strict command unit projections exceed frozen count/byte bounds")
        transcript = _ModelVerification(
            connection,
            namespace,
            binding,
            artifacts=artifacts,
            derive=derive_semantic_observation,
            _recovery=True,
        )
        if transcript.expected != set(keys):
            raise ValueError("strict command proof manifest membership changed")
        transcript.merge_deadlines(deadlines)
        state, calls = transcript.state, transcript.calls
        recoverable, uploaded = (prove_uploaded_responses(
            transcript, artifacts, external, deadlines,
        ) if state is not None and state.unresolved else (set(), []))
        if state is not None:
            transcript.verify((), deadlines=deadlines)
        accepted = {}
        for event in events:
            if event.event_type is not EventType.COVERAGE_BATCH_ACCEPTED:
                continue
            if state is None:
                raise ValueError("accepted MODEL batch has no initialized budget proof")
            request = replay_request(artifacts, binding, event)
            transcript.verify(
                request.results,
                deadlines=deadlines,
                request=request,
                before_sequence=event.sequence,
            )
            for result in request.results:
                digest = coverage_digest(result.key.model_dump(mode="json"))
                if digest in accepted:
                    raise ValueError("strict command proof has duplicate accepted units")
                accepted[digest] = result.model_dump(mode="json")
        units = [r for r in unit_rows if r["unit_digest"] is not None]
        if (
            len(units) != len(keys)
            or not set(accepted) <= set(expected)
            or {r["unit_digest"] for r in units} != set(expected)
            or any(
                r["unit_key"] != expected[r["unit_digest"]]
                or r["result"] != accepted.get(r["unit_digest"])
                for r in units
            )
        ):
            raise ValueError("strict command proof accepted projections conflict with source")
        if issued:
            store = PostgresCoverageStore(
                runtime.dsn,
                deployment_namespace=namespace,
                artifacts=artifacts,
                supported_model_profiles=(REVIEWER_PROFILE,),
                model_observation_deriver=derive_semantic_observation,
            )
            read_issued_report(store, connection, binding, issued[0], deadlines, external)
        settled_keys = recoverable | {
            coverage_digest(c["reservation"]["key"])
            for c in calls.values()
            if c["receipt"] is not None
        }
        if any(
            k.kind == "part"
            and coverage_digest(k.model_dump(mode="json")) not in accepted
            and coverage_digest(k.model_dump(mode="json")) not in settled_keys
            for k in keys
        ):
            if (
                proof is None
                or (state.calls if state is not None else 0) >= policy.max_calls
                or policy.max_tokens - (state.charged_tokens if state is not None else 0)
                < proof.context_window
            ):
                raise ValueError("strict continuation has no full-C remaining model budget")
        external()
        uploaded_only = [entry for entry in uploaded if str(entry[0].artifact_id) not in originals]
        if sum(row.reservation.size_bytes for row, _ in originals.values()) + sum(
            row.reservation.size_bytes for row, _, _ in uploaded_only
        ) > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("combined original response recovery exceeds bounded bytes")
        check_checkpoint_retention(connection, deadlines)
        if finalizers is not None:

            @postgres_connection_scope()
            def final_authority(deadline: float) -> None:
                from agent_storage.postgres.coverage_recovery_preparation import (
                    CoverageRecoveryDeferred,
                    remaining_recovery_time,
                )

                def final_external() -> None:
                    remaining_recovery_time(deadline)
                    try:
                        external()
                    except CoverageRefusedError as error:
                        if error.reason is CoverageRefusalReason.UPSTREAM_NOT_READY:
                            raise CoverageRecoveryDeferred("final Host proof unavailable") from None
                        raise

                with httpx.Client(
                    verify=True,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=remaining_recovery_time(deadline) / 4,
                ) as fresh:
                    gateway.transport = HttpHostToolTransport(
                        client=fresh, deadline_monotonic=deadline
                    )
                    final_external()
                    for record, digest in originals.values():
                        remaining_recovery_time(deadline)
                        original_receipt = record.object_receipt
                        if original_receipt is None:
                            raise ValueError("prepared original has no physical object version")
                        try:
                            data = cast(
                                S3ArtifactObjectStore, runtime.objects
                            ).read_version_verified_before(
                                original_receipt.expectation,
                                original_receipt.object_version,
                                deadline,
                            )
                        except TimeoutError:
                            raise CoverageRecoveryDeferred("final object proof timed out") from None
                        from hashlib import sha256

                        if sha256(data).digest() != digest:
                            raise ValueError("prepared original object changed before recovery")
                    fresh.timeout = httpx.Timeout(remaining_recovery_time(deadline) / 4)
                    revalidate_uploaded_responses(artifacts, uploaded, final_external, deadline)
                    final_external()
                    remaining_recovery_time(deadline)

            finalizers.append(final_authority)
        return {
            "session_id": str(session_id),
            "accepted_event_id": str(pending["accepted_event_id"]),
            "generation": receipt["wake_generation"],
            "floor": receipt["execution_floor_sequence"],
            "stream_revision": revision,
            "receipt_digest": coverage_digest(
                {
                    k: v if v is None or isinstance(v, str | int) else str(v)
                    for k, v in receipt.items()
                }
            ),
            "run_id": binding.run_id,
            "namespace": binding.namespace,
            "task_binding_digest": pinned.binding_digest,
            "source_watermark": run["source_watermark"],
            "source_digest": coverage_digest([e.model_dump(mode="json") for e in events]),
            "expected_count": len(keys),
            "expected_digest": coverage_digest([k.model_dump(mode="json") for k in keys]),
            "accepted_count": len(accepted),
            "uploaded_response_digest": uploaded_responses_digest(uploaded),
            "valid_until": min(deadlines).isoformat(),
        }
