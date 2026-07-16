from __future__ import annotations

import json
import os
import selectors
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Protocol

MAX_MCP_FRAME_BYTES = 64 * 1024
MCP_PROTOCOL_VERSION = "2025-06-18"
_SAFE_ENV_NAMES = ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")


class McpProtocolError(ValueError):
    """Raised when a configured MCP server violates the bounded protocol."""


class McpServerSpec(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def command(self) -> str: ...

    @property
    def args(self) -> Sequence[str]: ...


@dataclass
class StdioMcpSession:
    server: McpServerSpec
    timeout_seconds: float
    _process: subprocess.Popen[bytes] | None = field(default=None, init=False)
    _selector: selectors.BaseSelector | None = field(default=None, init=False)
    _buffer: bytearray = field(default_factory=bytearray, init=False)
    _request_id: int = field(default=0, init=False)
    _capabilities: dict[str, object] = field(default_factory=dict, init=False)
    _has_server_instructions: bool = field(default=False, init=False)

    def __enter__(self) -> StdioMcpSession:
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")
        env = {key: os.environ[key] for key in _SAFE_ENV_NAMES if key in os.environ}
        try:
            self._process = subprocess.Popen(
                [self.server.command, *self.server.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                shell=False,
            )
        except OSError as exc:
            raise McpProtocolError(f"MCP server {self.server.name} could not start") from exc
        assert self._process.stdout is not None
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._process.stdout, selectors.EVENT_READ)
        try:
            result = self.request(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "zebra-agent", "version": "0.1.0"},
                },
            )
            capabilities = result.get("capabilities")
            if not isinstance(capabilities, Mapping):
                raise McpProtocolError(f"MCP server {self.server.name} has invalid capabilities")
            self._capabilities = dict(capabilities)
            self._has_server_instructions = result.get("instructions") is not None
            self.notify("notifications/initialized")
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(self, method: str, params: Mapping[str, object] | None = None) -> dict[str, object]:
        self._request_id += 1
        request_id = self._request_id
        payload: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)
        self._send(payload)
        deadline = monotonic() + self.timeout_seconds
        while True:
            message = self._read_message(deadline)
            message_id = message.get("id")
            if type(message_id) is not int or message_id != request_id:
                if "method" in message and "id" not in message:
                    continue
                raise McpProtocolError(
                    f"MCP server {self.server.name} returned an unexpected message"
                )
            error = message.get("error")
            if error is not None:
                raise McpProtocolError(
                    f"MCP server {self.server.name} returned a protocol error"
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpProtocolError(
                    f"MCP server {self.server.name} returned an invalid result"
                )
            return result

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    @property
    def has_server_instructions(self) -> bool:
        return self._has_server_instructions

    def close(self) -> None:
        if self._selector is not None:
            self._selector.close()
            self._selector = None
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def _send(self, payload: Mapping[str, object]) -> None:
        process = self._require_process()
        assert process.stdin is not None
        frame = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        try:
            process.stdin.write(frame)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpProtocolError(f"MCP server {self.server.name} closed its input") from exc

    def _read_message(self, deadline: float) -> dict[str, object]:
        process = self._require_process()
        assert process.stdout is not None
        while b"\n" not in self._buffer:
            if len(self._buffer) > MAX_MCP_FRAME_BYTES:
                raise McpProtocolError(f"MCP server {self.server.name} returned an oversized frame")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise McpProtocolError(f"MCP server {self.server.name} timed out")
            assert self._selector is not None
            if not self._selector.select(remaining):
                raise McpProtocolError(f"MCP server {self.server.name} timed out")
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                raise McpProtocolError(f"MCP server {self.server.name} closed its output")
            self._buffer.extend(chunk)
        frame, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        if len(frame) > MAX_MCP_FRAME_BYTES:
            raise McpProtocolError(f"MCP server {self.server.name} returned an oversized frame")
        try:
            message = json.loads(
                frame,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise McpProtocolError(f"MCP server {self.server.name} returned invalid JSON") from exc
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise McpProtocolError(f"MCP server {self.server.name} returned an invalid message")
        return message

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise RuntimeError("MCP session is not open")
        return self._process


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
