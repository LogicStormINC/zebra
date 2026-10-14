"""Bounded Redis descriptors are locators, never execution or read authority."""

import json
from hashlib import sha256

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.leases import LeaseFence
from agent_core.ports.transient_output import TransientStreamScope
from pydantic import BaseModel, ConfigDict, Field


class TransientDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: TransientStreamScope
    fence: LeaseFence
    request_sequence: int = Field(strict=True, ge=1)


def transient_lane(
    namespace: str,
    authority: OpaqueAuthorityScope,
    task_id: str,
    segment_id: str,
    run_id: str,
    *,
    key_prefix: str = "zebra:transient:v2",
) -> str:
    lane = sha256(
        json.dumps(
            (namespace, authority.model_dump_json(), task_id, segment_id, run_id),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return f"{key_prefix}:{{{lane}}}"


DISCOVER = """
local t=redis.call('TIME'); local now=t[1]*1000+math.floor(t[2]/1000)
if redis.call('HGET',KEYS[1],'dirty')=='1' or
 redis.call('HGET',KEYS[1],'closed')~='0' or
 now>=tonumber(redis.call('HGET',KEYS[1],'expiry') or '0') then return {} end
local descriptor=redis.call('HGET',KEYS[1],'descriptor')
if not descriptor then return {} end
return {descriptor,redis.call('HGET',KEYS[1],'revision')}
"""


def discover(client: object, lane: str) -> tuple[TransientDescriptor, str] | None:
    result = client.eval(DISCOVER, 1, lane + ":authority")  # type: ignore[attr-defined]
    if not result:
        return None
    raw, revision = result
    if isinstance(raw, bytes):
        raw = raw.decode()
    if len(raw.encode()) > 8192:
        raise ValueError("transient descriptor exceeds budget")
    if isinstance(revision, bytes):
        revision = revision.decode()
    if not isinstance(revision, str) or len(revision) > 256:
        raise ValueError("transient descriptor revision is malformed")
    return TransientDescriptor.model_validate_json(raw), revision


def transient_aggregates(scope: TransientStreamScope, *, key_prefix: str) -> tuple[str, str, str]:
    """Verified identity only; a Run spans Segments, Turns and model calls."""
    def digest(parts: tuple[str, ...]) -> str:
        return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()

    authority = scope.authority_scope
    deployment = digest((scope.deployment_namespace,))
    tenant = digest((scope.deployment_namespace, *authority.scope_key))
    run = digest((scope.deployment_namespace, *authority.scope_key,
                  str(scope.generation.task_id), scope.generation.run_id))
    return f"{key_prefix}:capacity:{deployment}", tenant, run


def transient_deployment_key(namespace: str, *, key_prefix: str) -> str:
    digest = sha256(json.dumps((namespace,), separators=(",", ":")).encode()).hexdigest()
    return f"{key_prefix}:capacity:{digest}"
