import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import ArtifactId, SessionId
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_runtime import SetupPhasePlan, SetupPhaseRunner
from agent_security import SetupDownload, SetupEgressGateway, TemporarySetupCredential
from zebra_agent_config import SetupSettings, ZebraAgentSettings

from zebra_agent_worker.runtime_factory import build_runtime, build_runtime_spec
from zebra_agent_worker.runtime_instances import (
    BoundInstanceFactory,
)
from zebra_agent_worker.runtime_instances import (
    InstanceFactory as InstanceFactory,
)
from zebra_agent_worker.runtime_instances import (
    bind_instance_factory as bind_instance_factory,
)


class RuntimeSetupError(RuntimeError):
    """Raised when a setup-only task cannot produce a sealed Agent workspace."""


@dataclass(frozen=True)
class PreparedRuntime:
    handle: RuntimeHandle
    setup_artifact_id: ArtifactId | None = None
    compatible_authority_digests: tuple[str, ...] = ()


def build_prepared_runtime(
    settings: ZebraAgentSettings,
    database_path: Path,
    *,
    workspace_root: Path,
    network_profile: str,
    session_id: SessionId,
    attempt_number: int,
    artifact_store: ArtifactPayloadStorePort | None,
    created_at: datetime,
    instance_factory: BoundInstanceFactory | None = None,
    compatible_session_ids: tuple[str, ...] = (),
) -> tuple[RuntimePort, PreparedRuntime]:
    runtime = build_runtime(
        settings,
        database_path,
        workspace_root=workspace_root,
        network_profile="none" if network_profile == "setup-only" else network_profile,
        session_id=str(session_id),
        attempt_number=attempt_number,
        instance_factory=instance_factory,
    )
    prepared = prepare_runtime(
        runtime,
        setup=settings.setup,
        network_profile=network_profile,
        workspace_root=workspace_root,
        session_id=session_id,
        artifact_store=artifact_store,
        created_at=created_at,
    )
    compatible_digests = tuple(
        build_runtime_spec(
            settings,
            workspace_root=workspace_root,
            network_profile="none" if network_profile == "setup-only" else network_profile,
            session_id=compatible_session_id,
            attempt_number=attempt_number,
        ).digest
        for compatible_session_id in compatible_session_ids
        if compatible_session_id != str(session_id)
    )
    return runtime, PreparedRuntime(
        handle=prepared.handle,
        setup_artifact_id=prepared.setup_artifact_id,
        compatible_authority_digests=compatible_digests,
    )


def prepare_runtime(
    runtime: RuntimePort,
    *,
    setup: SetupSettings,
    network_profile: str,
    workspace_root: Path,
    session_id: SessionId,
    artifact_store: ArtifactPayloadStorePort | None,
    created_at: datetime,
) -> PreparedRuntime:
    if network_profile != "setup-only":
        return PreparedRuntime(handle=runtime.provision(workspace_root=str(workspace_root)))
    if not setup.enabled:
        raise RuntimeSetupError("setup-only network profile requires enabled Setup configuration")
    if artifact_store is None:
        raise RuntimeSetupError("setup-only runtime requires a local Artifact payload store")
    plan = SetupPhasePlan(
        command=setup.command,
        dependencies=tuple(
            SetupDownload(
                url=dependency.url,
                sha256=dependency.sha256,
                file_name=dependency.file_name,
            )
            for dependency in setup.dependencies
        ),
        lockfiles=setup.lockfiles,
    )
    token = None
    if setup.credential_env is not None:
        token = os.environ.get(setup.credential_env)
        if token is None or not token.strip():
            raise RuntimeSetupError("temporary Setup credential environment value is missing")
    credential = TemporarySetupCredential(token)
    gateway = SetupEgressGateway(
        allowed_domains=setup.allowed_domains,
        cache_root=workspace_root / ".zebra" / "setup-cache",
        credential=credential,
        max_dependency_bytes=setup.max_dependency_bytes,
    )
    result = SetupPhaseRunner(plan, gateway).run(runtime, workspace_root=workspace_root)
    try:
        artifact = artifact_store.store_payload(
            ArtifactPayloadWrite(
                session_id=session_id,
                kind="runtime.setup",
                mime_type="application/json",
                payload=result.artifact_payload,
                file_name="runtime-setup.json",
                created_at=created_at,
            )
        )
    except Exception:
        runtime.destroy(result.agent_handle)
        raise
    return PreparedRuntime(
        handle=result.agent_handle,
        setup_artifact_id=artifact.artifact_id,
    )


def require_matching_runtime_authority(
    handle: RuntimeHandle,
    persisted_digest: str | None,
    compatible_digests: tuple[str, ...] = (),
) -> None:
    authority = handle.authority
    accepted = {None, *compatible_digests}
    if authority is not None:
        accepted.add(authority.spec_digest)
    if authority is not None and persisted_digest not in accepted:
        raise RuntimeSetupError("configured runtime authority differs from session authority")


def destroy_runtime(runtime: RuntimePort | None, handle: RuntimeHandle | None) -> Exception | None:
    if runtime is None or handle is None:
        return None
    try:
        runtime.destroy(handle)
    except Exception as error:
        return error
    return None
