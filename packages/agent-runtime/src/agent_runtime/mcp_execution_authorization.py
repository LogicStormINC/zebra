"""Synchronous Broker resolver for one server-bound operation, not a public API."""

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from agent_core.domain.extensions import McpConnection
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.ports.lease_store import LeaseStorePort
from agent_core.ports.mcp_credentials import McpCredentialManagementStore
from agent_security.host_grant import VerifiedHostGrant
from agent_security.mcp_credential_release import McpCredentialRelease, require_live_mcp_authority
from agent_security.mcp_execution_authority import McpWorkerAuthority

from agent_runtime.mcp_http_authorization import McpHttpBearerCredential
from agent_runtime.mcp_protocol import MAX_MCP_FRAME_BYTES, McpProtocolError


@dataclass(frozen=True)
class McpExecutionCredentialResolver:
    """Trusted composition supplies recovered Turn/digest, current fence and policy-approved call.

    Run HTTP sessions on a blocking worker thread. Effectful calls must remain
    inside FencedEffectToolGateway; this resolver never creates a second ledger.
    """

    release: McpCredentialRelease = field(repr=False)
    leases: LeaseStorePort = field(repr=False)
    fresh_authority: Callable[[], VerifiedHostGrant | McpWorkerAuthority] = field(repr=False)
    session_id: SessionId
    turn_id: str
    snapshot_digest: str
    fence: LeaseFence
    connection_id: str
    endpoint: str
    method: Literal["tools/call", "resources/read", "prompts/get"]
    params_json: str = field(repr=False)
    connections: McpCredentialManagementStore | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        McpConnection.validate_endpoint(self.endpoint)
        if self.method not in ("tools/call", "resources/read", "prompts/get"):
            raise ValueError("unsupported MCP execution method")
        if len(self.params_json.encode()) > MAX_MCP_FRAME_BYTES:
            raise ValueError("MCP execution parameters exceed frame limit")
        params = json.loads(self.params_json)
        if not isinstance(params, dict):
            raise ValueError("MCP execution parameters must be an object")
        name = params.get("uri" if self.method == "resources/read" else "name")
        if not isinstance(name, str) or not name:
            raise ValueError("MCP execution requires a named operation")
        object.__setattr__(self, "params_json", _canonical(params))

    def _check_frame(self, endpoint: str, frame: Mapping[str, object]) -> None:
        if endpoint != self.endpoint:
            raise McpProtocolError("MCP execution endpoint mismatch")
        method = frame.get("method")
        if method not in ("initialize", "notifications/initialized") and (
            method != self.method or _canonical(frame.get("params")) != self.params_json
        ):
            raise McpProtocolError("MCP execution differs from the authorized operation")

    def authorize_anonymous(self, endpoint: str, frame: Mapping[str, object]) -> None:
        """Public endpoints still require current user authority and a live Worker fence."""
        self._check_frame(endpoint, frame)
        self._require_owned()
        if self.connections is None:
            raise McpProtocolError("MCP live connection authority unavailable")
        verified = self.fresh_authority()

        async def check() -> None:
            params = json.loads(self.params_json)
            kind: Literal["tools", "resources", "prompts"] = (
                "tools"
                if self.method == "tools/call"
                else "resources"
                if self.method == "resources/read"
                else "prompts"
            )
            current = await self.release.authorize_snapshot(
                verified=verified,
                session_id=str(self.session_id),
                turn_id=self.turn_id,
                expected_digest=self.snapshot_digest,
                connection_id=self.connection_id,
                endpoint=endpoint,
                kind=kind,
                name=params["uri" if kind == "resources" else "name"],
            )
            assert self.connections is not None
            latest = await self.connections.get_connection(
                scope=current.scope, connection_id=current.connection_id
            )
            if current.auth_mode.value != "none" or latest != current:
                raise McpProtocolError("MCP connection is no longer authorized")
            require_live_mcp_authority(verified)

        asyncio.run(check())
        self._require_owned()

    def __call__(self, endpoint: str, frame: Mapping[str, object]) -> McpHttpBearerCredential:
        self._check_frame(endpoint, frame)
        self._require_owned()
        verified = self.fresh_authority()
        params = json.loads(self.params_json)
        kind: Literal["tools", "resources", "prompts"] = (
            "tools"
            if self.method == "tools/call"
            else "resources"
            if self.method == "resources/read"
            else "prompts"
        )
        secret = asyncio.run(
            self.release.release(
                verified=verified,
                session_id=str(self.session_id),
                turn_id=self.turn_id,
                expected_digest=self.snapshot_digest,
                connection_id=self.connection_id,
                endpoint=self.endpoint,
                kind=kind,
                name=params["uri" if kind == "resources" else "name"],
            )
        )
        self._require_owned()
        return McpHttpBearerCredential(self.endpoint, secret)

    def _require_owned(self) -> None:
        lease = self.leases.get(self.session_id)
        if (
            lease is None
            or lease.session_id != self.session_id
            or lease.fence != self.fence
            or lease.expires_at <= datetime.now(UTC)
        ):
            raise LeaseLostError("MCP execution lease is no longer current")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
