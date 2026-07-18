from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

CommandName = Literal[
    "mcp-prompts",
    "run",
    "message",
    "cancel",
    "resume",
    "suspend",
    "inspect",
    "context",
    "handoff",
    "approval",
    "approve",
    "memory-review",
    "memory-bulk-review",
    "memory-review-queue",
    "memory-review-queue-preview",
    "memory-user-review",
    "memory-user-bulk-review",
    "memory-user-review-queue",
    "memory-user-review-queue-preview",
    "memory-tenant-review",
    "memory-tenant-bulk-review",
    "memory-tenant-review-queue",
    "memory-tenant-review-queue-preview",
    "model",
    "artifact",
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
    "commit",
    "pull-request",
]


@dataclass(frozen=True)
class CliCommandResult:
    command: CommandName
    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(
            {
                "command": self.command,
                **self.payload,
            },
            sort_keys=True,
        )
