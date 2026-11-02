"""Synthetic native-wire fixture: one read-only tool and declared fake usage."""

import json
import runpy
from http.server import ThreadingHTTPServer
from uuid import uuid4

fixture = runpy.run_path("/fixtures/fake_model.py")
base = fixture["_Handler"]
original_completion = fixture["_completion"]
original_completion.__globals__["_TOOL_CALL"]["function"]["arguments"] = json.dumps(
    {"command": ["pwd"]}
)


def completion(request):
    result = original_completion(request)
    result["id"] = f"e1-synthetic-{uuid4()}"
    result["model"] = request.get("model", "deepseek-v4-pro")
    result["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    result["choices"][0]["message"]["reasoning_content"] = ""
    return result


base.do_POST.__globals__["_completion"] = completion


class Handler(base):
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
