from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

CommandName = Literal[
    "run",
    "message",
    "cancel",
    "resume",
    "suspend",
    "inspect",
    "approval",
    "approve",
    "memory-review",
    "model",
    "artifact",
    "diff",
    "memory",
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
