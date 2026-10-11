"""Strict Cloud HTTP composition; ordinary creation and schedules remain separate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import signature
from typing import TYPE_CHECKING, Any

from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.application.session_bootstrap import BootstrappedSession
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.database import PostgresDatabase

from zebra_agent_api.api_command_mixin import _accepted_from_event, _bounded_run_key
from zebra_agent_api.idempotency import scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse, bad_request, service_unavailable
from zebra_agent_api.session_payloads import parse_create_session_payload

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


@dataclass(frozen=True)
class CoverageHttpAdmission:
    dsn: str
    namespace: str
    configuration_digest: str

    def preflight(self) -> None:
        """Read-only refusal before external effects; the write transaction rechecks."""
        from agent_storage.postgres.command_wakeup_handoff import handoff_command

        if "consumer_capability" not in signature(handoff_command).parameters:
            raise RuntimeError("strict native process routing is not composed")
        with PostgresDatabase(
            self.dsn, deployment_namespace=self.namespace
        ).connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            # No row locks in an observational transaction. Atomic admission pins later.
            from agent_storage.postgres.worker_capability import PostgresWorkerCapabilities

            rollout = connection.execute(
                "SELECT admission_enabled FROM command_wakeup_rollouts "
                "WHERE deployment_namespace=%s",
                (self.namespace,),
            ).fetchone()
            if rollout is None or not rollout["admission_enabled"]:
                raise RuntimeError("strict native admission rollout is unavailable")
        if not PostgresWorkerCapabilities(self.dsn, deployment_namespace=self.namespace).current(
            configuration_digest=self.configuration_digest,
        ):
            raise RuntimeError("strict native Worker is unavailable")


def initial_run(
    bootstrap: BootstrappedSession,
    idempotency_key: str | None,
) -> tuple[SessionEvent, dict[str, object]]:
    session = bootstrap.session
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=session.current_sequence,
        idempotency_key=_bounded_run_key(idempotency_key, str(session.session_id)),
    )
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=session.current_sequence + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=command.idempotency_key,
    )
    return event, _accepted_from_event(event, str(session.session_id)).body


def create_strict_session(
    api: ZebraAgentApi,
    payload: dict[str, object],
    *,
    idempotency_key: str | None,
    host_context: HostContextEnvelope | None,
    verified_host_grant: VerifiedHostGrant | None,
) -> ApiResponse:
    parsed = parse_create_session_payload(payload, structural_only=True)
    if isinstance(parsed, ApiResponse):
        return parsed
    composed = getattr(api, "coverage_http_admission", None)
    if type(composed) is not CoverageHttpAdmission:
        return service_unavailable(status="coverage_unsupported", reason="strict_worker_not_ready")
    if (
        parsed["attachments"]
        or parsed["workspace_source"] is not None
        or parsed["mcp_allowlist"]
        or parsed["mcp_resource_ids"]
        or parsed["mcp_prompt_id"]
        or parsed["skill_components"]
        or parsed["history_session_ids"]
        or parsed["definition_id"] is not None
    ):
        return service_unavailable(
            status="coverage_unsupported", reason="strict_options_unsupported"
        )
    if not parsed["execute"]:
        return bad_request("strict create requires execute=true for atomic RUN admission")
    if (
        verified_host_grant is None
        or type(verified_host_grant) is not VerifiedHostGrant
        or host_context is None
        or verified_host_grant.context != host_context
    ):
        return ApiResponse(403, {"status": "verified_host_grant_required"})
    try:
        admission = validate_coverage_admission(
            parsed["coverage_admission"],
            host_context=host_context,
            now=datetime.now(UTC),
        )
    except ValueError:
        return bad_request("coverage admission conflicts with Host authority or contract")
    if (
        admission.model_profile != api.settings.model.reviewer_profile
        or parsed["max_model_calls"] not in (None, admission.max_model_calls)
        or parsed["model_profile"] not in (None, admission.model_profile)
    ):
        return bad_request("coverage admission conflicts with configured profile or call ceiling")
    try:
        # Typed input was already reconstructed without extras. Hash canonical raw fields,
        # preserving the original request meaning for replay rather than normalized defaults.
        from agent_core.domain.coverage_task_admission import coverage_admission_input

        canonical_payload = dict(payload)
        canonical_payload["coverage_admission"] = coverage_admission_input(
            payload["coverage_admission"]
        )
        composed.preflight()
    except Exception:
        return service_unavailable(status="coverage_unsupported", reason="strict_worker_not_ready")
    from zebra_agent_api.session_binding import _compose_admission
    from zebra_agent_api.session_queue import create_queued_session

    key = scoped_idempotency_key(idempotency_key, host_context)
    kwargs = _compose_admission(api, host_context, canonical_payload, key, strict_composed=True)
    if isinstance(kwargs, ApiResponse):
        return kwargs
    if not isinstance(kwargs, dict) or "frozen_manifest_digest" not in kwargs:
        return service_unavailable(
            status="coverage_unsupported", reason="strict_manifest_not_frozen"
        )
    parsed["max_model_calls"] = admission.max_model_calls
    try:
        return create_queued_session(
            api.stores,
            parsed,
            host_context=host_context,
            verified_host_grant=verified_host_grant,
            coverage_configuration_digest=composed.configuration_digest,
            public_idempotency_key=idempotency_key,
            **kwargs,
        )
    except Exception:
        # Fixed response only; provider, DSN and binding exception text may contain secrets.
        return service_unavailable(
            status="coverage_admission_unavailable", reason="strict_native_refused"
        )


def compose_coverage_http_admission(settings: Any, stores: Any) -> CoverageHttpAdmission | None:
    from agent_storage import PostgresCloudArtifactPayloadStore, S3ArtifactObjectStore
    from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
    from agent_storage.worker_capability_configuration import worker_capability_configuration_digest

    reader = getattr(stores, "artifact_payload_reader", None)
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or type(reader) is not CloudArtifactPayloadReader
        or type(reader._objects) is not S3ArtifactObjectStore
        or not callable(getattr(reader._objects, "_deadline_client_factory", None))
        or type(reader._metadata) is not PostgresCloudArtifactPayloadStore
        or reader._namespace != getattr(stores, "deployment_namespace", None)
        or reader._metadata is not stores.artifact_payloads
        or reader._metadata._database._dsn != settings.database_url
        or reader._metadata._database.deployment_namespace != reader._namespace
    ):
        return None
    try:
        digest = worker_capability_configuration_digest(
            settings,
            namespace=reader._namespace,
            bucket=reader._objects._bucket,
            key_prefix=reader._objects._key_prefix,
            object_endpoint=getattr(
                getattr(reader._objects._client, "meta", None), "endpoint_url", None
            ),
        )
    except ValueError:
        return None
    return CoverageHttpAdmission(settings.database_url, reader._namespace, digest)
