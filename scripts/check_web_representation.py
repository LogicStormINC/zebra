"""uv run python scripts/check_web_representation.py; no framework, model or network."""

from datetime import UTC, datetime
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime.web_gateway import LocalWebGatewayTransport
from agent_tools.web_gateway import WebFetchTool


class Response:
    status = 200

    def __init__(self, body, content_type):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def check():
    source = "https://example.test/announcement/"
    markdown = b"# Release\nPublished: 2025-05-01\nVector set, JSON and data structures."
    html = b'<main>Published: 2025-05-01 <a href="/notes/">Notes</a></main>'
    for supports_markdown in (True, False):
        calls = []
        class Opener:
            def open(self, request, *, timeout, calls=calls, supported=supports_markdown):
                calls.append(request)
                accept = request.get_header("Accept")
                choices = dict((s.split(";")[0].strip(), float(s.split("q=")[-1])
                                if "q=" in s else 1.0) for s in accept.split(","))
                assert choices["text/markdown"] > choices["text/html"]
                assert all(choices[t] > 0 for t in ("text/plain", "text/html",
                                                   "application/json", "application/xml"))
                assert request.full_url == source and timeout == 10
                assert request.get_header("Accept-encoding") == "gzip"
                assert request.get_header("Authorization") is None
                return Response(markdown, "text/markdown") if supported else Response(
                    html, "text/html"
                )
        with patch("agent_runtime.web_gateway.urllib.request.build_opener", return_value=Opener()):
            result = WebFetchTool(LocalWebGatewayTransport()).handle(ToolCall(
                tool_call_id=new_tool_call_id(), name="web.fetch", arguments={"url": source},
                created_at=datetime.now(UTC),
            ))
        assert len(calls) == 1 and result.status is ToolCallStatus.EXECUTED
        assert result.output.startswith("[UNTRUSTED EXTERNAL CONTENT]")
        assert "2025-05-01" in result.output and result.metadata["url"] == source
        if not supports_markdown:
            assert result.metadata["evidence_refs"] == ["https://example.test/notes/"]
    with patch("agent_runtime.web_gateway.urllib.request.build_opener") as build:
        build.return_value.open.side_effect = HTTPError(source, 406, "unavailable", None, None)
        result = WebFetchTool(LocalWebGatewayTransport()).handle(ToolCall(
            tool_call_id=new_tool_call_id(), name="web.fetch", arguments={"url": source},
            created_at=datetime.now(UTC),
        ))
    assert result.status is ToolCallStatus.FAILED and build.return_value.open.call_count == 1
    print("Markdown preference, HTML fallback, exact source/untrusted receipt and no retry pass")


if __name__ == "__main__":
    check()
