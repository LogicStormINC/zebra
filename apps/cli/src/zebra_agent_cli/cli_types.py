from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

CommandName = Literal[
    "run",
    "resume",
    "suspend",
    "inspect",
    "approve",
    "model",
    "artifact",
    "diff",
    "stream",
    "delivery-audit",
    "commit",
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
