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

from zebra_agent_worker.runtime_factory import build_runtime


class RuntimeSetupError(RuntimeError):
    """Raised when a setup-only task cannot produce a sealed Agent workspace."""


@dataclass(frozen=True)
class PreparedRuntime:
    handle: RuntimeHandle
    setup_artifact_id: ArtifactId | None = None


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
) -> tuple[RuntimePort, PreparedRuntime]:
    runtime = build_runtime(
        settings,
        database_path,
        workspace_root=workspace_root,
        network_profile="none" if network_profile == "setup-only" else network_profile,
        session_id=str(session_id),
        attempt_number=attempt_number,
    )
    return runtime, prepare_runtime(
        runtime,
        setup=settings.setup,
        network_profile=network_profile,
        workspace_root=workspace_root,
        session_id=session_id,
        artifact_store=artifact_store,
        created_at=created_at,
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
) -> None:
    authority = handle.authority
    if authority is not None and persisted_digest not in {None, authority.spec_digest}:
        raise RuntimeSetupError("configured runtime authority differs from session authority")


def destroy_runtime(runtime: RuntimePort, handle: RuntimeHandle | None) -> Exception | None:
    if handle is None:
        return None
    try:
        runtime.destroy(handle)
    except Exception as error:
        return error
    return None
