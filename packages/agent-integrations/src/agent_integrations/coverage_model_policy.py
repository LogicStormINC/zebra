"""Explicit configured proof from trusted original official metadata, never a fetch.

Parsing bytes does NOT prove origin. The future composition must authenticate a
separate fresh client at MODELS_URL with trust_env=False/follow_redirects=False,
then supply the original bounded response here. No discovery occurs implicitly.
"""

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from agent_core.domain.coverage_persistence import canonical_coverage_bytes

from agent_integrations.coverage_snapshot_invocation import unique_object
from agent_integrations.deepseek_profiles import deepseek_profile

MODELS_URL = "https://api.deepseek.com/models"
CHAT_URL = "https://api.deepseek.com/chat/completions"
REVIEWER_PROFILE = "deepseek-v4-pro-reviewer-v1"
POLICY_VERSION = "coverage-deepseek-official/1"
POLICY_KIND = "coverage-model-policy-internal"
MAX_METADATA_BYTES = 1024 * 1024


def _nonfinite(value: str) -> Any:
    raise ValueError("nonfinite official model metadata")


@dataclass(frozen=True)
class OfficialDeepSeekPolicy:
    original_metadata: bytes
    metadata_url: str = MODELS_URL
    chat_url: str = CHAT_URL
    version: str = POLICY_VERSION
    context_window: int = field(init=False)
    max_output_tokens: int = field(init=False)
    supported_effort_levels: tuple[str, ...] = field(init=False)
    default_effort_level: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.original_metadata) is not bytes
            or not 0 < len(self.original_metadata) <= MAX_METADATA_BYTES
            or any(
                type(value) is not str for value in (self.metadata_url, self.chat_url, self.version)
            )
            or self.metadata_url != MODELS_URL
            or self.chat_url != CHAT_URL
            or self.version != POLICY_VERSION
        ):
            raise ValueError("unsupported official metadata origin/configuration or size")
        try:
            data = json.loads(
                self.original_metadata.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=_nonfinite,
            )
            # Validate every string and number, including unconsumed provider fields.
            canonical_coverage_bytes(data)
            if (
                type(data) is not dict
                or data.get("object") != "list"
                or type(data.get("data")) is not list
                or any(type(row) is not dict for row in data["data"])
            ):
                raise ValueError("unsupported official model list")
            model = deepseek_profile(REVIEWER_PROFILE).model
            rows = [row for row in data["data"] if row.get("id") == model]
            if len(rows) != 1:
                raise ValueError("official reviewer model must be unique")
            row = rows[0]
            capacity, output = row.get("context_window"), row.get("max_output_tokens")
            effort = row.get("effort")
            if type(effort) is not dict or set(effort) != {"supported_levels", "default_level"}:
                raise ValueError("official reviewer requires explicit effort proof")
            levels, default = effort["supported_levels"], effort["default_level"]
            if (
                row.get("object") != "model"
                or row.get("owned_by") != "deepseek"
                or ("created" in row and (type(row["created"]) is not int or row["created"] < 0))
                or type(capacity) is not int
                or capacity <= 0
                or type(output) is not int
                or not 8192 <= output <= capacity
                or row.get("input_modalities") != ["text"]
                or row.get("output_modalities") != ["text"]
                or type(levels) is not list
                or any(type(level) is not str for level in levels)
                or len(set(levels)) != len(levels)
                or "high" not in levels
                or type(default) is not str
                or default not in levels
            ):
                raise ValueError("official reviewer lacks explicit full capacity/text/HIGH proof")
        except (UnicodeError, RecursionError, OverflowError) as error:
            raise ValueError("invalid original official metadata") from error
        object.__setattr__(self, "context_window", capacity)
        object.__setattr__(self, "max_output_tokens", output)
        object.__setattr__(self, "supported_effort_levels", tuple(sorted(levels)))
        object.__setattr__(self, "default_effort_level", default)

    @property
    def effective(self) -> dict[str, object]:
        profile = deepseek_profile(REVIEWER_PROFILE)
        return {
            "version": self.version,
            "metadata_url": self.metadata_url,
            "chat_url": self.chat_url,
            "provider": "deepseek",
            "model": profile.model,
            "profile": REVIEWER_PROFILE,
            "prompt_version": profile.prompt_version,
            "profile_version": profile.version_observed_at,
            "context_window": self.context_window,
            "capacity_semantics": "input-plus-output",
            "max_output_tokens": self.max_output_tokens,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "reasoning_effort": "high",
            "effort": {
                "supported_levels": list(self.supported_effort_levels),
                "default_level": self.default_effort_level,
            },
            "thinking": "enabled",
            "role": "reviewer",
            "tool_choice": "none",
            "request_max_output_tokens": 8192,
            "retries": 0,
        }

    @property
    def capacity_hash(self) -> str:
        return sha256(canonical_coverage_bytes(self.effective)).hexdigest()
