"""Private Native evaluator composition; no HTTP boolean/evidence import API."""

import argparse
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from agent_core.domain.bundle_definition import BundleDefinitionVersion
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from agent_core.domain.native_script import NativeScript
from agent_core.domain.native_script_protocol import ScriptRunResult
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.script_bundle import ScriptRuntimeAssembly
from agent_core.ports.runtime import RuntimePort, SandboxSpec
from agent_runtime.native_script_eval import ScriptEvalSuite, evaluate_scripts
from agent_runtime.native_script_runtime import ScopedNativeScriptRunner
from agent_storage.postgres.agent_registry import AgentDefinitionEvalEvidence
from agent_storage.postgres.script_evaluation import ScriptEvaluationStore
from zebra_agent_config import ZebraAgentSettings, load_settings
from zebra_agent_config.private_configuration import read_private_configuration

from zebra_agent_worker.native_scripts import approved_scripts
from zebra_agent_worker.runtime_factory import build_runtime, build_runtime_spec


def run_evaluation(
    settings: ZebraAgentSettings,
    suite_path: Path,
    operation: UUID,
    *,
    mode: str = "evaluate",
    namespace: str = "local",
) -> dict[str, object]:
    # Optional operator command requires the existing publisher adapter installed.
    # Normal Worker/API startup never imports this module or adds a runner dependency.
    from zebra_agent_api.publication_config import load_publication_approval

    if mode not in {"initialize", "evaluate", "read"}:
        raise ValueError("INVALID_EVAL_MODE")
    store = ScriptEvaluationStore(settings.database_url, namespace)
    if mode == "initialize":
        store.initialize()
        return {"initialized": True}
    approval = load_publication_approval(settings.publication_management_config, namespace)
    suite_bytes = read_private_configuration(str(suite_path), max_bytes=131072)
    suite = ScriptEvalSuite.model_validate(load_bundle_json(suite_bytes))
    version = store.registry.get_version(
        approval.definition_scope, AgentDefinitionVersionId(suite.version_id)
    )
    if (
        not isinstance(version, BundleDefinitionVersion)
        or not isinstance(version.runtime_assembly, ScriptRuntimeAssembly)
        or version.definition_digest != suite.definition_digest
        or suite.definition_id != approval.definition_id
        or suite.scope != approval.scope
        or suite.evaluator_actor not in approval.evaluator_actors
        or suite.policy_version != approval.policy_version
        or "publish" not in approval.actions
    ):
        raise PermissionError("EVAL_APPROVAL_REQUIRED")
    assembly = version.runtime_assembly
    assert isinstance(assembly, ScriptRuntimeAssembly)
    required = {
        assembly.required_reference,
        "runtime-bundle/" + assembly.bundle.bundle_digest.removeprefix("sha256:") + "@1",
    }
    if not required <= set(approval.references):
        raise PermissionError("EVAL_REFERENCE_DENIED")
    suite.check(assembly)
    deadline = datetime.now(UTC) + timedelta(seconds=65)

    def recheck() -> None:
        current = load_publication_approval(settings.publication_management_config, namespace)
        if (
            current != approval
            or read_private_configuration(str(suite_path), max_bytes=131072) != suite_bytes
        ):
            raise PermissionError("EVAL_APPROVAL_CHANGED")
        if datetime.now(UTC) >= deadline:
            raise TimeoutError("EVAL_DEADLINE")
        approved_scripts(settings, assembly)

    recheck()
    if mode == "read":
        found = store.observe(approval.trust, operation)
        if found is None:
            raise LookupError("EVAL_OPERATION_NOT_OBSERVABLE")
        if found["inputDigest"] != suite.digest:
            raise ValueError("EVAL_OPERATION_CONFLICT")
        recheck()
        return found
    claimed, receipt = store.claim(
        approval.trust,
        operation,
        suite.digest,
        approval.definition_scope.scope_key,
        suite.version_id,
        recheck,
    )
    if not claimed:
        recheck()
        return receipt  # unknown and completed are both observations, never execution retries.

    def authorize() -> None:
        recheck()
        store.approvals.read(approval.trust)

    def factory(workspace: Path) -> tuple[RuntimePort, SandboxSpec]:
        spec = build_runtime_spec(
            settings,
            workspace_root=workspace,
            network_profile="none",
            session_id=str(operation),
            attempt_number=1,
        )
        spec = replace(
            spec,
            workspace_writable=False,
            limits=replace(
                spec.limits,
                max_output_bytes=min(spec.limits.max_output_bytes, 32768),
                max_execution_seconds=min(spec.limits.max_execution_seconds, 30),
            ),
        )
        return build_runtime(
            settings,
            Path("."),
            workspace_root=workspace,
            network_profile="none",
            spec_override=spec,
        ), spec

    def execute(script: NativeScript, raw: bytes) -> ScriptRunResult:
        return ScopedNativeScriptRunner(assembly.native_scripts.runner, factory).run(
            script,
            raw,
            cancellation_check=authorize,
        )

    summary = evaluate_scripts(
        suite,
        assembly,
        authorize=authorize,
        execute=execute,
        source=lambda digest: approved_scripts(settings, assembly).script_for(digest),
    )
    # The evidence identity is the original operation UUID, fixed before execution.
    evidence = AgentDefinitionEvalEvidence(
        authority_issuer=suite.scope.authority_issuer,
        namespace_id=suite.scope.namespace_id,
        definition_id=AgentDefinitionId(suite.definition_id),
        version_id=AgentDefinitionVersionId(suite.version_id),
        evidence_id=operation,
        definition_digest=suite.definition_digest,
        passed=summary["passed"] is True,
        evaluator_actor=suite.evaluator_actor,
        case_summary=summary,
    )
    return store.complete(approval.trust, operation, suite.digest, evidence, summary, recheck)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="local")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--operation", type=UUID, required=True)
    parser.add_argument("--mode", choices=("initialize", "evaluate", "read"), default="evaluate")
    args = parser.parse_args()
    try:
        result = run_evaluation(
            load_settings(), args.suite, args.operation, mode=args.mode, namespace=args.namespace
        )
    except Exception:
        # No private config, source, credentials or arbitrary exception body in operator output.
        raise SystemExit(
            "EVAL_UNAVAILABLE; observe the original operation; do not automatically rerun"
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
