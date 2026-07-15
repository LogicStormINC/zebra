from __future__ import annotations

import argparse

from agent_core.domain.tool_profiles import ToolProfile
from agent_security import NetworkProfileName, PolicyProfile

from zebra_agent_cli.read_commands import add_read_subparsers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zebra-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="Create a local agent task.")
    run.add_argument("prompt")
    run.add_argument("--title", default="Untitled task")
    run.add_argument("--workspace", default=".")
    run.add_argument("--database")
    run.add_argument("--execute", action="store_true")
    run.add_argument(
        "--policy-profile",
        choices=tuple(profile.value for profile in PolicyProfile),
        default=PolicyProfile.WORKSPACE_WRITE.value,
    )
    run.add_argument(
        "--tool-profile",
        choices=tuple(profile.value for profile in ToolProfile),
        default=ToolProfile.GENERAL.value,
    )
    run.add_argument(
        "--network-profile",
        choices=tuple(profile.value for profile in NetworkProfileName),
        default=NetworkProfileName.NONE.value,
    )
    run.add_argument("--network-allowlist", action="append", default=[])

    message = subcommands.add_parser(
        "message",
        help="Append one more user message to an existing session.",
    )
    message.add_argument("session_id")
    message.add_argument("--content", required=True)
    message.add_argument("--clarification-id")
    message.add_argument("--database")

    cancel = subcommands.add_parser("cancel", help="Cancel a local session.")
    cancel.add_argument("session_id")
    cancel.add_argument("--database")

    resume = subcommands.add_parser("resume", help="Resume a suspended session.")
    resume.add_argument("session_id")
    resume.add_argument("--database")
    resume.add_argument("--execute", action="store_true")
    resume.add_argument("--worker-id", default="local-worker")
    resume.add_argument("--lease-ttl-seconds", type=int, default=30)

    suspend = subcommands.add_parser("suspend", help="Suspend a local session.")
    suspend.add_argument("session_id")
    suspend.add_argument("--database")

    inspect = subcommands.add_parser("inspect", help="Inspect a session.")
    inspect.add_argument("session_id")
    inspect.add_argument("--database")

    add_read_subparsers(subcommands)

    commit = subcommands.add_parser("commit", help="Create one local commit for a session.")
    commit.add_argument("session_id")
    commit.add_argument("--message", required=True)
    commit.add_argument("--author-name", default="Zebra Agent")
    commit.add_argument("--author-email", default="zebra-agent@example.local")
    commit.add_argument("--idempotency-key")
    commit.add_argument("--database")

    pull_request = subcommands.add_parser(
        "pull-request",
        help="Open one session pull request plan or guarded execution.",
    )
    pull_request.add_argument("session_id")
    pull_request.add_argument("--title", required=True)
    pull_request.add_argument("--body", default="")
    pull_request.add_argument("--base-branch", default="main")
    pull_request.add_argument("--head-branch")
    pull_request.add_argument("--execute", action="store_true")
    pull_request.add_argument("--idempotency-key")
    pull_request.add_argument("--database")

    artifact = subcommands.add_parser("artifact", help="Inspect or read session artifacts.")
    artifact_subcommands = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_subcommands.add_parser("list", help="List session artifacts.")
    artifact_list.add_argument("session_id")
    artifact_list.add_argument("--database")
    artifact_inspect = artifact_subcommands.add_parser(
        "inspect",
        help="Inspect one session artifact.",
    )
    artifact_inspect.add_argument("session_id")
    artifact_inspect.add_argument("artifact_id")
    artifact_inspect.add_argument("--database")
    artifact_read = artifact_subcommands.add_parser(
        "read",
        help="Read one payload-backed session artifact.",
    )
    artifact_read.add_argument("session_id")
    artifact_read.add_argument("artifact_id")
    artifact_read.add_argument("--database")
    artifact_prune = artifact_subcommands.add_parser(
        "prune",
        help="Prune one managed payload-backed session artifact.",
    )
    artifact_prune.add_argument("session_id")
    artifact_prune.add_argument("artifact_id")
    artifact_prune.add_argument("--database")

    approve = subcommands.add_parser("approve", help="Record an approval decision.")
    approve.add_argument("session_id")
    approve.add_argument("--decision", choices=("approve", "reject"), required=True)
    approve.add_argument("--reason", default="")
    approve.add_argument("--operator", default="local-operator")
    approve.add_argument("--database")

    memory_review = subcommands.add_parser(
        "memory-review",
        help="Record a memory candidate review decision.",
    )
    memory_review.add_argument("session_id")
    memory_review.add_argument("memory_id")
    memory_review.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_review.add_argument("--reason", default="")
    memory_review.add_argument("--operator", default="local-operator")
    memory_review.add_argument("--database")

    memory_bulk_review = subcommands.add_parser(
        "memory-bulk-review",
        help="Record bulk memory candidate review decisions for one session scope.",
    )
    memory_bulk_review.add_argument("session_id")
    memory_bulk_review.add_argument("memory_ids", nargs="+")
    memory_bulk_review.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_bulk_review.add_argument("--reason", default="")
    memory_bulk_review.add_argument("--operator", default="local-operator")
    memory_bulk_review.add_argument("--database")

    memory_review_queue = subcommands.add_parser(
        "memory-review-queue",
        help="Review the current session-scoped memory queue in one action.",
    )
    memory_review_queue.add_argument("session_id")
    memory_review_queue.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_review_queue.add_argument("--reason", default="")
    memory_review_queue.add_argument("--operator", default="local-operator")
    memory_review_queue.add_argument("--database")

    memory_review_queue_preview = subcommands.add_parser(
        "memory-review-queue-preview",
        help="Preview the current session-scoped memory queue review target set.",
    )
    memory_review_queue_preview.add_argument("session_id")
    memory_review_queue_preview.add_argument(
        "--decision", choices=("confirm", "expire"), required=True
    )
    memory_review_queue_preview.add_argument("--memory-type")
    memory_review_queue_preview.add_argument("--database")

    memory_user_review = subcommands.add_parser(
        "memory-user-review",
        help="Record a user-scoped memory candidate review decision.",
    )
    memory_user_review.add_argument("user_id")
    memory_user_review.add_argument("memory_id")
    memory_user_review.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_user_review.add_argument("--reason", default="")
    memory_user_review.add_argument("--operator", default="local-operator")
    memory_user_review.add_argument("--database")

    memory_user_bulk_review = subcommands.add_parser(
        "memory-user-bulk-review",
        help="Record bulk user-scoped memory candidate review decisions.",
    )
    memory_user_bulk_review.add_argument("user_id")
    memory_user_bulk_review.add_argument("memory_ids", nargs="+")
    memory_user_bulk_review.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_user_bulk_review.add_argument("--reason", default="")
    memory_user_bulk_review.add_argument("--operator", default="local-operator")
    memory_user_bulk_review.add_argument("--database")

    memory_user_review_queue = subcommands.add_parser(
        "memory-user-review-queue",
        help="Review the current user-scoped memory queue in one action.",
    )
    memory_user_review_queue.add_argument("user_id")
    memory_user_review_queue.add_argument(
        "--decision", choices=("confirm", "expire"), required=True
    )
    memory_user_review_queue.add_argument("--reason", default="")
    memory_user_review_queue.add_argument("--operator", default="local-operator")
    memory_user_review_queue.add_argument("--database")

    memory_user_review_queue_preview = subcommands.add_parser(
        "memory-user-review-queue-preview",
        help="Preview the current user-scoped memory queue review target set.",
    )
    memory_user_review_queue_preview.add_argument("user_id")
    memory_user_review_queue_preview.add_argument(
        "--decision", choices=("confirm", "expire"), required=True
    )
    memory_user_review_queue_preview.add_argument("--memory-type")
    memory_user_review_queue_preview.add_argument("--database")

    memory_tenant_review = subcommands.add_parser(
        "memory-tenant-review",
        help="Record a tenant-scoped memory candidate review decision.",
    )
    memory_tenant_review.add_argument("tenant_id")
    memory_tenant_review.add_argument("memory_id")
    memory_tenant_review.add_argument("--decision", choices=("confirm", "expire"), required=True)
    memory_tenant_review.add_argument("--reason", default="")
    memory_tenant_review.add_argument("--operator", default="local-operator")
    memory_tenant_review.add_argument("--database")

    memory_tenant_bulk_review = subcommands.add_parser(
        "memory-tenant-bulk-review",
        help="Record bulk tenant-scoped memory candidate review decisions.",
    )
    memory_tenant_bulk_review.add_argument("tenant_id")
    memory_tenant_bulk_review.add_argument("memory_ids", nargs="+")
    memory_tenant_bulk_review.add_argument(
        "--decision",
        choices=("confirm", "expire"),
        required=True,
    )
    memory_tenant_bulk_review.add_argument("--reason", default="")
    memory_tenant_bulk_review.add_argument("--operator", default="local-operator")
    memory_tenant_bulk_review.add_argument("--database")

    memory_tenant_review_queue = subcommands.add_parser(
        "memory-tenant-review-queue",
        help="Review the current tenant-scoped memory queue in one action.",
    )
    memory_tenant_review_queue.add_argument("tenant_id")
    memory_tenant_review_queue.add_argument(
        "--decision",
        choices=("confirm", "expire"),
        required=True,
    )
    memory_tenant_review_queue.add_argument("--reason", default="")
    memory_tenant_review_queue.add_argument("--operator", default="local-operator")
    memory_tenant_review_queue.add_argument("--database")

    memory_tenant_review_queue_preview = subcommands.add_parser(
        "memory-tenant-review-queue-preview",
        help="Preview the current tenant-scoped memory queue review target set.",
    )
    memory_tenant_review_queue_preview.add_argument("tenant_id")
    memory_tenant_review_queue_preview.add_argument(
        "--decision",
        choices=("confirm", "expire"),
        required=True,
    )
    memory_tenant_review_queue_preview.add_argument("--memory-type")
    memory_tenant_review_queue_preview.add_argument("--database")

    model = subcommands.add_parser("model", help="Run one prompt through the configured model.")
    model.add_argument("prompt")

    return parser
