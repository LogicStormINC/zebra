from __future__ import annotations

import json
import sys
from pathlib import Path


def send(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
marker = Path(sys.argv[2]) if len(sys.argv) > 2 else None

for raw_line in sys.stdin:
    message = json.loads(raw_line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture", "version": "1"},
                },
            }
        )
    elif method == "tools/list":
        if mode == "invalid-json":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            continue
        schema: object = (
            {"type": "string"}
            if mode == "malformed-schema"
            else {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            }
        )
        tool_count = 17 if mode == "too-many-tools" else 1
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo" if index == 0 else f"echo{index}",
                            "description": "Echo one value.",
                            "inputSchema": schema,
                        }
                        for index in range(tool_count)
                    ]
                },
            }
        )
    elif method == "tools/call":
        if marker is not None:
            marker.write_text("called", encoding="utf-8")
        params = message.get("params", {})
        value = params.get("arguments", {}).get("value", "") if isinstance(params, dict) else ""
        if mode == "env":
            import os

            value = "secret-present" if os.environ.get("DEEPSEEK_API_KEY") else "secret-absent"
        elif mode == "oversized-output":
            value = "x" * (33 * 1024)
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": f"echo:{value}"}]},
            }
        )
