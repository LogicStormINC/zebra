"""HTTP input evidence is distinct from generated-output Worker lease authority."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.cloud_artifact_requests import ArtifactReserveRequest
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import EventId, SessionId


def registry_policy_digest(record: dict[str, Any]) -> str:
    keys = ('host_app_id', 'namespace_id', 'issuer', 'audience', 'jwks_uri',
            'allowed_origins', 'algorithms', 'policy_version', 'active')
    return sha256(json.dumps({key: record[key] for key in keys}, sort_keys=True,
                            separators=(',', ':')).encode()).hexdigest()


class ConsumedHostGrantProof(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    deployment_namespace: str
    grant_id: str
    grant_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    expires_at: datetime
    authority_issuer: str
    algorithm: str
    audit_id: int = Field(gt=0)
    policy_version: str
    trust_policy_revision: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def aware_expiry(self):
        if self.expires_at.tzinfo is None:
            raise ValueError('consumed Host proof expiry must be timezone aware')
        return self


class HttpInputAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    context: HostContextEnvelope
    proof: ConsumedHostGrantProof
    task_id: str
    binding_digest: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def matching_consumed_claims(self):
        if (self.context.grant_id != self.proof.grant_id
            or self.context.expires_at != self.proof.expires_at
            or self.context.policy_version != self.proof.policy_version):
            raise ValueError('HTTP input proof does not match verified context')
        return self


@dataclass(frozen=True, slots=True)
class PreparedHttpInputAttachment:
    reference: SessionAttachmentRef
    reservation: ArtifactReserveRequest
    receipt: ArtifactObjectReceipt


@dataclass(frozen=True, slots=True)
class PreparedHttpInputBatch:
    authority: HttpInputAuthority
    session_id: SessionId
    event_id: EventId
    entries: tuple[PreparedHttpInputAttachment, ...]
