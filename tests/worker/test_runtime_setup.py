import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from agent_core.domain.identifiers import new_session_id
from agent_core.ports.runtime import RuntimeClass, SandboxSpec
from agent_runtime import OsSandboxRuntime
from agent_storage import SQLiteArtifactPayloadStore
from zebra_agent_config import SetupDependencySettings, SetupSettings
from zebra_agent_worker.runtime_setup import RuntimeSetupError, prepare_runtime


def _settings(*, enabled: bool = True) -> SetupSettings:
    return SetupSettings(
        enabled=enabled,
        command=("/bin/sh", "-c", "test -f .zebra/setup-cache/package.whl"),
        allowed_domains=("files.example.test",),
        dependencies=(
            SetupDependencySettings(
                url="https://files.example.test/package.whl",
                sha256=hashlib.sha256(b"wheel").hexdigest(),
                file_name="package.whl",
            ),
        ),
        lockfiles=("uv.lock",),
        credential_env="TEMP_SETUP_TOKEN",
    )


def _runtime(workspace: Path, state: Path) -> OsSandboxRuntime:
    def runner(command, **kwargs) -> CompletedProcess[str]:
        return CompletedProcess(tuple(command), 0, "ok", "")

    return OsSandboxRuntime(
        SandboxSpec(
            runtime_class=RuntimeClass.OS_SANDBOX,
            image="",
            workspace_root=str(workspace),
            engine="sandbox-exec",
        ),
        system="Darwin",
        finder=lambda _: "/usr/bin/sandbox-exec",
        runner=runner,
        snapshot_root=state,
    )


def test_prepare_runtime_runs_setup_stores_evidence_and_returns_agent_handle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "uv.lock").write_text("locked", encoding="utf-8")
    monkeypatch.setenv("TEMP_SETUP_TOKEN", "temporary-secret")
    monkeypatch.setattr(
        "agent_security.setup_egress._download_without_redirects",
        lambda *args, **kwargs: b"wheel",
    )
    store = SQLiteArtifactPayloadStore(tmp_path / "sessions.sqlite")

    prepared = prepare_runtime(
        _runtime(workspace, tmp_path / "state"),
        setup=_settings(),
        network_profile="setup-only",
        workspace_root=workspace,
        session_id=new_session_id(),
        artifact_store=store,
        created_at=datetime.now(UTC),
    )

    assert prepared.handle.authority is not None
    assert prepared.handle.authority.network_enforcement == "os-sandbox-network-deny"
    assert prepared.setup_artifact_id is not None
    payload = store.read_payload_bytes(prepared.setup_artifact_id)
    assert json.loads(payload)["credential_revoked"] is True
    assert b"temporary-secret" not in payload


def test_prepare_runtime_fails_closed_when_setup_is_disabled(tmp_path: Path) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "sessions.sqlite")

    with pytest.raises(RuntimeSetupError, match="requires enabled"):
        prepare_runtime(
            _runtime(tmp_path, tmp_path / "state"),
            setup=SetupSettings(),
            network_profile="setup-only",
            workspace_root=tmp_path,
            session_id=new_session_id(),
            artifact_store=store,
            created_at=datetime.now(UTC),
        )
