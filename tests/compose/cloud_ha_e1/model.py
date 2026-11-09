"""Synthetic native-wire fixture: one read-only tool and declared fake usage."""

import json
import runpy
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from metering import measured_usage

fixture = runpy.run_path(str(Path(__file__).with_name("fake_model.py")))
base = fixture["_Handler"]
original_completion = fixture["_completion"]
original_completion.__globals__["_TOOL_CALL"]["function"]["arguments"] = json.dumps(
    {"command": ["pwd"]}
)


def completion(request):
    if not isinstance(request, dict):
        raise ValueError("fixture request must be an object")
    result = original_completion(request)
    messages = request.get("messages", [])
    # ponytail: an explicit user marker selects the fixed E1-A no-tool workload.
    if isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and "[zebra-ha-e1-short-v1]" in message["content"]
        for message in messages
    ):
        result["choices"][0]["message"] = {"role": "assistant", "content": "E1 short completed."}
        result["choices"][0]["finish_reason"] = "stop"
    result["id"] = f"e1-synthetic-{uuid4()}"
    result["model"] = request.get("model", "deepseek-v4-pro")
    result["choices"][0]["message"]["reasoning_content"] = ""
    result["usage"] = measured_usage(request, result["choices"][0]["message"])
    return result


base.do_POST.__globals__["_completion"] = completion


class Handler(base):
    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4 * 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                raise ValueError("fixture wire outside supported bound")
            super().do_POST()
        except ValueError:
            self.close_connection = True
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "fixture_meter_contract_rejected"})

    def _write_stream(self, response):
        choice = response["choices"][0]
        delta = dict(choice["message"])
        if "tool_calls" in delta:
            delta["tool_calls"] = [
                dict(call, index=i) for i, call in enumerate(delta["tool_calls"])
            ]
        events = [
            dict(
                id=response["id"],
                model=response["model"],
                choices=[dict(index=0, delta=delta, finish_reason=choice["finish_reason"])],
            ),
            dict(id=response["id"], model=response["model"], choices=[], usage=response["usage"]),
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Zebra-E1-Synthetic-Usage", "true")
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 28082), Handler).serve_forever()
