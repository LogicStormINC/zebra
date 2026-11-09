"""Probe only the pinned fixture through the committed native SSE decoder."""

import json
import runpy
from pathlib import Path

import httpx
from agent_integrations.openai_streaming import read_openai_stream
from metering import encode, measure_request

runpy.run_path(str(Path(__file__).with_name("check_model.py")))
with httpx.Client(trust_env=False, timeout=5) as client:
    body = {
        "model": "deepseek-v4-pro", "stream": True, "max_tokens": 1024,
        "tools": [{"type": "function", "function": {
            "name": "command__run", "parameters": {"type": "object"}}}],
        "messages": [{"role": "user", "content": "E1 synthetic read-only probe"}],
    }
    result = read_openai_stream(
        client,
        url="https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer synthetic-only"},
        body=body,
        on_text_delta=lambda _: None,
    )
proof = measure_request(encode(body))
usage = result["usage"]
assert usage["prompt_tokens"] == proof.input_upper_bound
assert 0 < usage["completion_tokens"] <= proof.output_cap
assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
call = result["choices"][0]["message"]["tool_calls"][0]
assert json.loads(call["function"]["arguments"]) == {"command": ["pwd"]}
print("Native SSE tool decoding and synthetic usage fields verified; no Task created.")
