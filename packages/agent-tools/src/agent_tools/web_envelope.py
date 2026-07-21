from __future__ import annotations

from dataclasses import asdict, dataclass, field

from agent_core.domain.web import TruncationScope

from agent_tools.mcp_proxy import JsonValue

#: Stable capability version for the native web result envelope. Keep aligned
#: with contract compatibility policy when required fields or output semantics
#: change in a backward-incompatible way (see WEB-PIPE-CON-01).
WEB_ENVELOPE_CAPABILITY_VERSION = "2"


@dataclass(frozen=True)
class WebResultEnvelope:
    """Provider-neutral web result envelope.

    Web tools populate this and fold it into ``ToolResult.metadata`` under
    ``web_envelope``. Provider-specific diagnostics live in ``extra`` and never
    become required cross-provider model contract.
    """

    provider: str
    capability_version: str
    fetched_at: str
    canonical_url: str
    truncation_scope: TruncationScope
    truncated: bool
    untrusted_external_content: bool = True
    provider_version: str | None = None
    content_type: str | None = None
    content_sha256: str | None = None
    resource_id: str | None = None
    artifact_uri: str | None = None
    degraded: bool = False
    citations: tuple[str, ...] = ()
    freshness: str | None = None
    evidence_score: float | None = None
    extra: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("web envelope provider must not be blank")
        if not self.capability_version.strip():
            raise ValueError("web envelope capability_version must not be blank")
        if not self.fetched_at.strip():
            raise ValueError("web envelope fetched_at must not be blank")
        if not self.canonical_url.strip():
            raise ValueError("web envelope canonical_url must not be blank")
        if self.truncated and self.truncation_scope is TruncationScope.NONE:
            raise ValueError(
                "web envelope truncation_scope must not be NONE when truncated"
            )
        if self.evidence_score is not None and not 0.0 <= self.evidence_score <= 1.0:
            raise ValueError("web envelope evidence_score must be within [0.0, 1.0]")

    def to_metadata(self) -> dict[str, JsonValue]:
        metadata = asdict(self)
        metadata["truncation_scope"] = self.truncation_scope.value
        metadata["citations"] = list(self.citations)
        return metadata
