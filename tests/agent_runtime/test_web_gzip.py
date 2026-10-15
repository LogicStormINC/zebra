"""Compressed responses retain both wire and decoded-body safety bounds."""

import gzip
import io
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from agent_core.domain.web import parse_web_target
from agent_runtime.web_gateway import LocalWebGatewayTransport, _read_bounded_body
from agent_tools.web_gateway import WebGatewayError, WebGatewayRequest


def response(body: bytes, encoding: str = "gzip", *, length: int | None = None):
    value = io.BytesIO(body)
    value.headers = {"Content-Encoding": encoding}  # type: ignore[attr-defined]
    if length is not None:
        value.headers["Content-Length"] = str(length)  # type: ignore[attr-defined]
    return value


def test_gzip_body_is_decoded_with_same_content():
    body = b"official announcement " * 100
    packed = gzip.compress(body)
    assert _read_bounded_body(response(packed, length=len(packed)), len(body)) == body


@pytest.mark.parametrize("wire", [False, True])
def test_gzip_enforces_wire_and_decoded_caps(wire):
    packed = gzip.compress(b"x" * 5000)
    maximum = len(packed) - 1 if wire else 100
    with pytest.raises(WebGatewayError) as caught:
        _read_bounded_body(response(packed), maximum)
    assert caught.value.reason == "response_too_large"


@pytest.mark.parametrize("body", [b"not gzip", gzip.compress(b"release")[:-1],
                                 gzip.compress(b"release") + b"garbage",
                                 gzip.compress(b"release")[:10] + b"\x07" +
                                 gzip.compress(b"release")[11:]])
def test_corrupt_or_truncated_gzip_is_not_a_success(body):
    with pytest.raises(WebGatewayError) as caught:
        _read_bounded_body(response(body), 100)
    assert caught.value.reason == "response_incomplete"


def test_wire_content_length_still_checks_compressed_bytes():
    packed = gzip.compress(b"release")
    with pytest.raises(WebGatewayError) as caught:
        _read_bounded_body(response(packed, length=len(packed) + 1), 100)
    assert caught.value.reason == "response_incomplete"


def test_identity_and_concatenated_members():
    assert _read_bounded_body(response(b"release", "identity", length=7), 7) == b"release"
    assert _read_bounded_body(response(gzip.compress(b"a") + gzip.compress(b"b")), 100) == b"ab"


def test_fetch_advertises_only_supported_gzip_and_keeps_projection(monkeypatch):
    original = b"<main><h1>Official release</h1></main>"
    packed = gzip.compress(original)
    result = Mock()
    result.headers.get.side_effect = lambda key, default=None: {
        "Content-Type": "text/html", "Content-Encoding": "gzip",
        "Content-Length": str(len(packed)),
    }.get(key, default)
    result.headers.get_content_charset.return_value = "utf-8"
    result.read.return_value = packed
    result.status = 200
    opener = Mock()
    opener.open.return_value = nullcontext(result)
    monkeypatch.setattr("urllib.request.build_opener", lambda *a: opener)
    monkeypatch.setattr("agent_runtime.web_gateway._proxy_configuration", lambda *a, **kw: {})
    fetched = LocalWebGatewayTransport().execute(WebGatewayRequest(
        tool_call_id="fixed", target=parse_web_target("https://example.com/release")))
    assert opener.open.call_args.args[0].get_header("Accept-encoding") == "gzip"
    assert "Official release" in fetched.text and "<main>" not in fetched.text
    assert fetched.byte_count == len(original)
