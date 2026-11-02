"""Probe only the pinned fixture through the committed native SSE decoder."""

import json
import runpy
from pathlib import Path

import httpx
from agent_integrations.openai_streaming import read_openai_stream

runpy.run_path(str(Path(__file__).with_name("check_model.py")))
with httpx.Client(trust_env=False, timeout=5) as client:
    result = read_openai_stream(
        client,
        url="https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer synthetic-only"},
        body={
            "model": "deepseek-v4-pro",
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "command__run",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "messages": [{"role": "user", "content": "E1 synthetic read-only probe"}],
        },
        on_text_delta=lambda _: None,
    )
assert result["usage"] == {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
call = result["choices"][0]["message"]["tool_calls"][0]
assert json.loads(call["function"]["arguments"]) == {"command": ["pwd"]}
print("Native SSE tool decoding and synthetic usage fields verified; no Task created.")
