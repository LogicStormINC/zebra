"""Host Grant claim assembly and RS256 signing.

The claim set mirrors `agent_core.domain.host_authority.HostSessionGrant`
exactly: the verifier validates with `extra="forbid"`, so no additional
claims (threadId/runId as top-level keys) may be emitted. Thread and run
binding travels in `resource_refs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.trench_session import TrenchViewer


class GrantMintError(ValueError):
    """Raised when an exchange request does not match broker policy."""


@dataclass(frozen=True, slots=True)
class ExchangeRequest:
    audience: str
    thread_id: str
    run_id: str
    scopes: tuple[str, ...]
    resource_refs: tuple[tuple[str, str], ...] = ()

    @classmethod
    def parse(cls, body: dict[str, object]) -> ExchangeRequest:
        if not isinstance(body, dict):
            raise GrantMintError("request_body_invalid")
        audience = _text(body.get("audience"), "audience")
        thread_id = _text(body.get("threadId"), "threadId")
        run_id = _text(body.get("runId"), "runId")
        raw_scopes = body.get("scopes")
        if not isinstance(raw_scopes, list) or not raw_scopes or len(raw_scopes) > 64:
            raise GrantMintError("scopes_invalid")
        scopes = tuple(_text(item, "scope") for item in raw_scopes)
        if len(set(scopes)) != len(scopes):
            raise GrantMintError("scopes_duplicated")
        resource_refs = _resource_refs(body.get("resourceRefs", []))
        return cls(
            audience=audience,
            thread_id=thread_id,
            run_id=run_id,
            scopes=scopes,
            resource_refs=resource_refs,
        )

    def enforce(self, settings: BrokerSettings) -> None:
        if self.audience != settings.audience:
            raise GrantMintError("audience_mismatch")
        unknown = [scope for scope in self.scopes if scope not in settings.allowed_scopes]
        if unknown:
            raise GrantMintError("scope_not_allowed")

    def authorize(self, viewer: TrenchViewer) -> None:
        requested_sources = {
            resource_id
            for resource_type, resource_id in self.resource_refs
            if resource_type == "trench.source"
        }
        if requested_sources - viewer.active_source_ids:
            raise GrantMintError("source_not_allowed")
        if self.resource_refs and not requested_sources:
            raise GrantMintError("source_binding_required")
        required_scopes = {
            "trench.event": "event.read",
            "trench.entity": "entity.read",
            "trench.topic": "topic.read",
        }
        for resource_type, _resource_id in self.resource_refs:
            required_scope = required_scopes.get(resource_type)
            if required_scope is not None and required_scope not in self.scopes:
                raise GrantMintError("resource_scope_missing")


def mint_grant(
    settings: BrokerSettings,
    signing_key: rsa.RSAPrivateKey,
    request: ExchangeRequest,
    viewer: TrenchViewer,
    *,
    now: datetime | None = None,
    jti: str | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    grant_id = jti or str(uuid4())
    claims = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": viewer.user_id,
        "jti": grant_id,
        "iat": int(issued_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=settings.ttl_seconds)).timestamp()),
        "host_app_id": settings.host_app_id,
        "namespace_id": settings.namespace_id,
        "workspace_ref": viewer.workspace_id or settings.workspace_ref,
        "resource_refs": [
            {"type": "thread", "id": request.thread_id},
            {"type": "run", "id": request.run_id},
            *(
                {"type": resource_type, "id": resource_id}
                for resource_type, resource_id in request.resource_refs
            ),
        ],
        "scopes": sorted(request.scopes),
        "limits": {
            "max_runtime_seconds": settings.max_runtime_seconds,
            "max_model_tokens": settings.max_model_tokens,
            "max_artifact_bytes": settings.max_artifact_bytes,
        },
        "origin": settings.origin,
        "policy_version": settings.policy_version,
    }
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": settings.key_id})


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise GrantMintError(f"{name}_invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > 512:
        raise GrantMintError(f"{name}_invalid")
    return normalized


def _resource_refs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or len(value) > 128:
        raise GrantMintError("resource_refs_invalid")
    allowed_types = {"trench.source", "trench.event", "trench.entity", "trench.topic"}
    refs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise GrantMintError("resource_refs_invalid")
        resource_type = _text(item.get("type"), "resource_type")
        resource_id = _text(item.get("id"), "resource_id")
        ref = (resource_type, resource_id)
        if resource_type not in allowed_types or ref in refs:
            raise GrantMintError("resource_refs_invalid")
        refs.append(ref)
    return tuple(refs)
