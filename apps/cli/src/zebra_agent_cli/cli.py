from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import build_model_gateway
from zebra_agent_api.session_context_control import SessionContextControlApi
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_cli.cli_database import (
    _database_path,
)
from zebra_agent_cli.cli_parser import build_parser
from zebra_agent_cli.cli_types import CliCommandResult
from zebra_agent_cli.command_result_builders import (
    _approval_result,
    _artifact_result,
    _suspend_result,
)
from zebra_agent_cli.mcp_prompt_commands import mcp_prompt_inventory
from zebra_agent_cli.memory_review_write import (
    preview_queue_memory_review,
    preview_queue_tenant_memory_review,
    preview_queue_user_memory_review,
    record_bulk_memory_review,
    record_bulk_tenant_memory_review,
    record_bulk_user_memory_review,
    record_memory_review,
    record_queue_memory_review,
    record_queue_tenant_memory_review,
    record_queue_user_memory_review,
    record_tenant_memory_review,
    record_user_memory_review,
)
from zebra_agent_cli.read_commands import read_command_result
from zebra_agent_cli.run_command_execution import (
    _run_result,
)
from zebra_agent_cli.session_cancel_write import cancel_session
from zebra_agent_cli.session_command_execution import (
    _resume_result,
    _session_result,
)
from zebra_agent_cli.session_commit_write import commit_session
from zebra_agent_cli.session_message_append_write import append_session_message
from zebra_agent_cli.session_pull_request_write import open_session_pull_request


def execute(
    argv: Sequence[str],
    *,
    settings: ZebraAgentSettings | None = None,
) -> CliCommandResult:
    namespace = build_parser().parse_args(list(argv))
    active_settings = settings or load_settings()
    command = namespace.command
    if command == "run":
        return _run_result(namespace, active_settings)
    if command == "mcp-prompts":
        return mcp_prompt_inventory(active_settings)
    if command == "message":
        return CliCommandResult(
            command="message",
            payload=append_session_message(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                content=namespace.content,
                clarification_id=namespace.clarification_id,
            ),
        )
    if command == "cancel":
        return CliCommandResult(
            command="cancel",
            payload=cancel_session(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
            ),
        )
    if command == "resume":
        return _resume_result(namespace, active_settings)
    if command == "suspend":
        return _suspend_result(namespace, active_settings)
    if command == "inspect":
        return _session_result(
            "inspect",
            namespace.session_id,
            _database_path(namespace.database, active_settings),
        )
    if command == "context":
        control = SessionContextControlApi(_database_path(namespace.database, active_settings))
        if namespace.context_command == "inspect":
            response = control.inspect(namespace.session_id)
        elif namespace.context_command == "recover":
            response = control.recover(
                namespace.session_id, {"capsule_id": namespace.capsule_id}
            )
        else:
            response = control.compact(
                namespace.session_id,
                {
                    "focus": namespace.focus,
                    "preview": namespace.preview,
                    "through_sequence": namespace.through_sequence,
                },
            )
        return CliCommandResult(
            command="context",
            payload={"action": namespace.context_command, **response.body},
        )
    if command == "approve":
        return _approval_result(namespace, _database_path(namespace.database, active_settings))
    if command == "memory-review":
        return CliCommandResult(
            command="memory-review",
            payload=record_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                memory_id=namespace.memory_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-bulk-review":
        return CliCommandResult(
            command="memory-bulk-review",
            payload=record_bulk_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                memory_ids=list(namespace.memory_ids),
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-review-queue":
        return CliCommandResult(
            command="memory-review-queue",
            payload=record_queue_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-review-queue-preview":
        return CliCommandResult(
            command="memory-review-queue-preview",
            payload=preview_queue_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                decision=namespace.decision,
                memory_type=namespace.memory_type,
            ),
        )
    if command == "memory-user-review":
        return CliCommandResult(
            command="memory-user-review",
            payload=record_user_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                user_id=namespace.user_id,
                memory_id=namespace.memory_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-user-bulk-review":
        return CliCommandResult(
            command="memory-user-bulk-review",
            payload=record_bulk_user_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                user_id=namespace.user_id,
                memory_ids=list(namespace.memory_ids),
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-user-review-queue":
        return CliCommandResult(
            command="memory-user-review-queue",
            payload=record_queue_user_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                user_id=namespace.user_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-user-review-queue-preview":
        return CliCommandResult(
            command="memory-user-review-queue-preview",
            payload=preview_queue_user_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                user_id=namespace.user_id,
                decision=namespace.decision,
                memory_type=namespace.memory_type,
            ),
        )
    if command == "memory-tenant-review":
        return CliCommandResult(
            command="memory-tenant-review",
            payload=record_tenant_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                tenant_id=namespace.tenant_id,
                memory_id=namespace.memory_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-tenant-bulk-review":
        return CliCommandResult(
            command="memory-tenant-bulk-review",
            payload=record_bulk_tenant_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                tenant_id=namespace.tenant_id,
                memory_ids=list(namespace.memory_ids),
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-tenant-review-queue":
        return CliCommandResult(
            command="memory-tenant-review-queue",
            payload=record_queue_tenant_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                tenant_id=namespace.tenant_id,
                decision=namespace.decision,
                operator=namespace.operator,
                reason=namespace.reason,
            ),
        )
    if command == "memory-tenant-review-queue-preview":
        return CliCommandResult(
            command="memory-tenant-review-queue-preview",
            payload=preview_queue_tenant_memory_review(
                database_path=_database_path(namespace.database, active_settings),
                tenant_id=namespace.tenant_id,
                decision=namespace.decision,
                memory_type=namespace.memory_type,
            ),
        )
    if command == "artifact":
        return _artifact_result(namespace, _database_path(namespace.database, active_settings))
    if command == "approval":
        return read_command_result(
            command,
            database_path=_database_path(namespace.database, active_settings),
            approval_id=getattr(namespace, "approval_id", None),
        )
    if command in {
        "diff",
        "memory",
        "memory-action-hints",
        "memory-escalations",
        "memory-follow-up-windows",
        "memory-overdue-flags",
        "memory-overdue-age-buckets",
        "memory-overdue-types",
        "memory-overdue-visibility",
        "memory-overdue-trends",
        "memory-overdue-interventions",
        "memory-overdue-escalation-lanes",
        "memory-overdue-recovery-paths",
        "memory-overdue-resolution-checkpoints",
        "memory-overdue-resolution-outcomes",
        "memory-overdue-closure-decisions",
        "memory-overdue-archive-recommendations",
        "memory-overdue-retention-guidance",
        "memory-overdue-retention-windows",
        "memory-overdue-retention-breaches",
        "memory-overdue-retention-breach-aging",
        "memory-overdue-retention-breach-actions",
        "memory-overdue-retention-breach-lanes",
        "memory-overdue-retention-breach-owner-targets",
        "memory-overdue-retention-breach-follow-through-modes",
        "memory-overdue-retention-breach-follow-through-outcomes",
        "memory-overdue-retention-breach-follow-through-completion-states",
        "memory-overdue-retention-breach-follow-through-verification-states",
        "memory-overdue-retention-breach-follow-through-verification-outcomes",
        "memory-aging",
        "memory-governance",
        "memory-overview",
        "memory-pressure",
        "memory-velocity",
        "memory-queue",
        "memory-queue-summary",
        "memory-user",
        "memory-user-queue",
        "memory-user-queue-summary",
        "memory-tenant",
        "memory-tenant-queue",
        "memory-tenant-queue-summary",
        "stream",
        "delivery-audit",
    }:
        return read_command_result(
            command,
            database_path=_database_path(namespace.database, active_settings),
            session_id=getattr(namespace, "session_id", None),
            user_id=getattr(namespace, "user_id", None),
            tenant_id=getattr(namespace, "tenant_id", None),
            as_of=getattr(namespace, "as_of", None),
        )
    if command == "commit":
        return CliCommandResult(
            command="commit",
            payload=commit_session(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                message=namespace.message,
                author_name=namespace.author_name,
                author_email=namespace.author_email,
                idempotency_key=namespace.idempotency_key,
            ),
        )
    if command == "pull-request":
        return CliCommandResult(
            command="pull-request",
            payload=open_session_pull_request(
                database_path=_database_path(namespace.database, active_settings),
                session_id=namespace.session_id,
                title=namespace.title,
                body=namespace.body,
                base_branch=namespace.base_branch,
                head_branch=namespace.head_branch,
                dry_run=not namespace.execute,
                idempotency_key=namespace.idempotency_key,
                settings=active_settings,
            ),
        )
    if command == "model":
        return _model_result(namespace, active_settings)
    raise ValueError(f"unsupported CLI command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
    result = execute(argv or ())
    print(result.to_json())
    return 0


def _model_result(
    namespace: argparse.Namespace,
    settings: ZebraAgentSettings,
) -> CliCommandResult:
    completion = build_model_gateway(settings).complete(
        [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=namespace.prompt,
                created_at=datetime.now(UTC),
            )
        ]
    )
    return CliCommandResult(
        command="model",
        payload={
            "prompt": namespace.prompt,
            "response": completion.assistant_message.content,
            "provider": completion.call_metadata.provider,
            "model_name": completion.call_metadata.model_name,
            "latency_ms": completion.call_metadata.latency_ms,
            "input_tokens": completion.call_metadata.usage.input_tokens,
            "output_tokens": completion.call_metadata.usage.output_tokens,
            "total_tokens": completion.call_metadata.usage.total_tokens,
            "tool_calls": [
                {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in completion.tool_calls
            ],
        },
    )
