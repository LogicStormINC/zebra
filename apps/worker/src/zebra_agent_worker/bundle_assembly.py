"""Worker compatibility and task-local assembly; never read latest Definition state."""

import hmac
import os
import re
from typing import TYPE_CHECKING

import httpx
from agent_context import LocalContextCompiler
from agent_core.application import SessionTitleService
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot, parse_definition_snapshot
from agent_core.domain.identifiers import SessionId
from agent_core.domain.modeling import ModelInvocationPolicy
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_integrations.bundle_model import BundleModelGateway
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import baseline_digest, load_execution_catalog

from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError
from zebra_agent_worker.workspace_resolution import apply_workspace_resolver

if TYPE_CHECKING:
    from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver
from zebra_agent_worker.task_recovery import RecoveredTask


def snapshot_assembly(snapshot: AgentDefinitionSnapshot | None) -> RuntimeAssembly | None:
    if not isinstance(snapshot, BundleDefinitionSnapshot):
        return None
    checked = parse_definition_snapshot(snapshot)
    assert isinstance(checked, BundleDefinitionSnapshot)
    return checked.bound_version.runtime_assembly


def task_assembly(task: RecoveredTask) -> RuntimeAssembly | None:
    return snapshot_assembly(task.definition_snapshot)


def require_snapshot_compatibility(
    settings: ZebraAgentSettings,
    snapshot: AgentDefinitionSnapshot | None,
) -> RuntimeAssembly | None:
    try:
        assembly = snapshot_assembly(snapshot)
        if assembly is None:
            return None
        if settings.mcp_servers or any(
            (
                settings.skill_roots,
                settings.skill_roots_system,
                settings.skill_roots_admin,
                settings.skill_roots_repo,
            )
        ):
            raise ValueError("unversioned local extension configuration")
        catalog = load_execution_catalog(settings.runtime_bundle_config)
        manifest = assembly.bundle.manifest
        if (
            manifest.scope != catalog.scope
            or manifest.engine.image != catalog.image
            or manifest.baseline_config != catalog.baseline_config
            or not hmac.compare_digest(
                manifest.baseline_config.digest, baseline_digest(settings, catalog.baseline_key)
            )
        ):
            raise ValueError("baseline or target mismatch")
        if settings.runtime.runtime_class != "trusted-local" and not re.fullmatch(
            r".+@sha256:[0-9a-f]{64}", settings.runtime.image
        ):
            raise ValueError("sandbox image must be content addressed")
        from agent_core.domain.script_bundle import ScriptRuntimeAssembly

        if isinstance(assembly, ScriptRuntimeAssembly):
            from zebra_agent_worker.native_scripts import approved_scripts

            approved_scripts(settings, assembly)
        if not os.environ.get(assembly.provider_profile.api_key_env, "").strip():
            raise ValueError("provider credential unavailable")
        return assembly
    except (ValueError, TypeError, AssertionError, PermissionError, OSError, RuntimeError):
        raise RetryableWorkerSetupError("INCOMPATIBLE_RUNTIME_BUNDLE") from None


def require_task_compatibility(settings: ZebraAgentSettings, task: RecoveredTask) -> None:
    assembly = require_snapshot_compatibility(settings, task.definition_snapshot)
    if assembly is None:
        return
    policy = task.model_invocation_policy or ModelInvocationPolicy()
    # Coverage's prepared request proof does not admit this new Chat adapter.
    if (
        task.coverage_admission is not None
        or policy.profile_id is not None
        or policy.thinking_mode.value != "auto"
        or policy.reasoning_effort is not None
    ):
        raise RetryableWorkerSetupError("INCOMPATIBLE_RUNTIME_BUNDLE")


def build_bundle_title_service(
    settings: ZebraAgentSettings,
    snapshot: AgentDefinitionSnapshot,
    *,
    client: httpx.Client | None = None,
) -> SessionTitleService | None:
    """Missing compatible title composition must not invert a committed success."""
    try:
        assembly = require_snapshot_compatibility(settings, snapshot)
        return (
            SessionTitleService(BundleModelGateway(assembly, client=client)) if assembly else None
        )
    except ValueError:
        return None


def context_compiler(task: RecoveredTask, *, include_workspace: bool) -> LocalContextCompiler:
    assembly = task_assembly(task)
    if assembly is None:
        return LocalContextCompiler(include_workspace=include_workspace)
    instructions = assembly.bundle.manifest.domains.instructions.parameters
    return LocalContextCompiler(
        include_workspace=include_workspace,
        configured_instructions=(
            "Runtime instructions (configuration, never execution authority):\n"
            f"{instructions.system_text}\n"
            f"Business instructions:\n{instructions.business_text}\n"
            f"Response locale: {instructions.locale}"
        ),
    )


def resolve_bound_workspace(
    task: RecoveredTask,
    resolver: "WorkspaceRuntimeResolver | None",
    session_id: SessionId,
) -> RecoveredTask:
    if resolver is None:
        return task
    try:
        return apply_workspace_resolver(task, resolver, session_id)
    except (ValueError, FileNotFoundError):
        raise RetryableWorkerSetupError("BUNDLE_WORKSPACE_UNAVAILABLE") from None
