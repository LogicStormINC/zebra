from __future__ import annotations

import pytest
from agent_core.domain.web import TruncationScope
from agent_tools.web_envelope import WEB_ENVELOPE_CAPABILITY_VERSION, WebResultEnvelope


def _envelope(**overrides: object) -> WebResultEnvelope:
    base: dict[str, object] = {
        "provider": "searxng",
        "capability_version": WEB_ENVELOPE_CAPABILITY_VERSION,
        "fetched_at": "2026-07-21T00:00:00Z",
        "canonical_url": "https://example.com/page",
        "truncation_scope": TruncationScope.NONE,
        "truncated": False,
    }
    base.update(overrides)
    return WebResultEnvelope(**base)  # type: ignore[arg-type]


def test_envelope_defaults_mark_content_untrusted() -> None:
    envelope = _envelope()

    assert envelope.untrusted_external_content is True
    metadata = envelope.to_metadata()
    assert metadata["untrusted_external_content"] is True
    assert metadata["truncation_scope"] == "none"
    assert metadata["citations"] == []


def test_truncated_requires_non_none_scope() -> None:
    with pytest.raises(ValueError):
        _envelope(truncated=True, truncation_scope=TruncationScope.NONE)


@pytest.mark.parametrize(
    "field,value",
    (
        ("provider", ""),
        ("capability_version", " "),
        ("fetched_at", ""),
        ("canonical_url", ""),
    ),
)
def test_envelope_rejects_blank_required_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _envelope(**{field: value})


def test_evidence_score_must_be_within_unit_interval() -> None:
    with pytest.raises(ValueError):
        _envelope(evidence_score=1.5)
    # boundary values are accepted
    assert _envelope(evidence_score=0.0).evidence_score == 0.0
    assert _envelope(evidence_score=1.0).evidence_score == 1.0


def test_metadata_carries_provider_specific_extra_without_polluting_contract() -> None:
    envelope = _envelope(extra={"searxng_engine": "google"})

    assert envelope.to_metadata()["extra"] == {"searxng_engine": "google"}
