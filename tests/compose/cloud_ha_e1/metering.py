"""E1-only accounting: canonical JSON UTF-8 bytes, never provider tokenizer tokens."""

import json
from hashlib import sha256

from agent_core.ports.worker_budget import ModelRequestBudget

CONTRACT = "e1-canonical-json-utf8-bytes/1"


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def measure_request(exact):
    if not isinstance(exact, bytes) or not 0 < len(exact) <= 4 * 1024 * 1024:
        raise ValueError("fixture request outside bounded wire contract")
    request = json.loads(exact)
    if not isinstance(request, dict) or encode(request) != exact:
        raise ValueError("fixture requires canonical object wire")
    return ModelRequestBudget(
        exact, sha256(exact).hexdigest(), len(exact), request.get("max_tokens"), CONTRACT
    )


def measured_usage(request, message):
    proof = measure_request(encode(request))
    output = len(encode(message))
    if output > proof.output_cap:
        raise ValueError("fixture message bytes exceed request output cap")
    return {"prompt_tokens": proof.input_upper_bound, "completion_tokens": output,
            "total_tokens": proof.input_upper_bound + output}
