"""Deterministic OpenAI-compatible SSE stub for the effect default E2E gate.

The stub is deliberately provider-shaped: the real Worker dials it through
the production ``OpenAICompatibleModelGateway`` client, so tool-call pairing
and stream decoding stay on the committed code path.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIDE_EFFECT_MARKER = os.environ.get("ZEBRA_EFFECT_E2E_MARKER", "WRITE-FILE")
SIDE_EFFECT_COMMAND = os.environ.get(
    "ZEBRA_EFFECT_E2E_COMMAND",
    '["sh", "-c", "printf effect-e2e-proof > effect-proof.txt"]',
)
SLOW_COMMAND = os.environ.get(
    "ZEBRA_EFFECT_E2E_SLOW_COMMAND",
    '["sh", "-c", "sleep 15; printf lease-loss-proof > lease-proof.txt"]',
)
HANG_MARKER = os.environ.get("ZEBRA_EFFECT_E2E_HANG_MARKER", "HANG-AFTER-TOOL")
HANG_SECONDS = float(os.environ.get("ZEBRA_EFFECT_E2E_HANG_SECONDS", "120"))
HANG_FLAG_DIR = os.environ.get("ZEBRA_EFFECT_E2E_FLAG_DIR", "/tmp/zebra-effect-e2e-flags")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        user_prompt = ""
        for message in body.get("messages", []):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    user_prompt = content
        command_tool = next(
            (
                tool["function"]["name"]
                for tool in body.get("tools", [])
                if isinstance(tool, dict)
                and "command" in str(tool.get("function", {}).get("name", "")).lower()
            ),
            None,
        )
        has_tool_result = any(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in body.get("messages", [])
        )
        slow = "SLOW-FILE" in user_prompt
        flags = Path(HANG_FLAG_DIR)
        if has_tool_result and HANG_MARKER in user_prompt and not (flags / "hang-used").exists():
            flags.mkdir(parents=True, exist_ok=True)
            (flags / "hang-used").write_text("1")
            (flags / "hang-started").write_text("1")
            time.sleep(HANG_SECONDS)
        wants_side_effect = (
            SIDE_EFFECT_MARKER in user_prompt and not has_tool_result and command_tool is not None
        )
        call_id = f"effect-e2e-call-{int(self.headers.get('X-Call-Seq', '0') or 0)}"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def chunk(payload: dict) -> None:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())

        if wants_side_effect:
            selected = SLOW_COMMAND if slow else SIDE_EFFECT_COMMAND
            arguments = json.dumps({"command": json.loads(selected)})
            chunk(
                {
                    "id": call_id,
                    "model": "effect-e2e-stub",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "effect-e2e-tool-1",
                                        "type": "function",
                                        "function": {
                                            "name": command_tool,
                                            "arguments": arguments,
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
            chunk(
                {
                    "id": call_id,
                    "model": "effect-e2e-stub",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                }
            )
        else:
            chunk(
                {
                    "id": call_id,
                    "model": "effect-e2e-stub",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "no tools required"},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            chunk(
                {
                    "id": call_id,
                    "model": "effect-e2e-stub",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, fmt: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler)
    server.serve_forever()
