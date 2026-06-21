from pathlib import Path

from agent_context.models import ContextItemKind, TrustLevel

_TRUSTED_FILENAMES = {
    "agents.md",
    "readme.md",
    "pyproject.toml",
    "makefile",
}
_SUSPICIOUS_PATTERNS = {
    "ignore previous instructions": "instruction_override",
    "system prompt": "system_prompt_reference",
    "exfiltrate": "exfiltration_language",
    "reveal secrets": "secret_request",
    "curl http": "network_execution_hint",
    "sudo rm -rf": "destructive_command",
}


def trust_level_for_item(
    *,
    kind: ContextItemKind,
    locator: str,
) -> TrustLevel:
    normalized_locator = locator.lower()
    if kind is ContextItemKind.REPO_MAP:
        return TrustLevel.SYSTEM
    if any(normalized_locator.endswith(name) for name in _TRUSTED_FILENAMES):
        return TrustLevel.TRUSTED
    if kind in {
        ContextItemKind.CONVERSATION_SUMMARY,
        ContextItemKind.TOOL_OUTPUT_SUMMARY,
    }:
        return TrustLevel.USER
    return TrustLevel.UNTRUSTED


def prompt_injection_metadata(content: str, locator: str) -> dict[str, object]:
    normalized_content = content.lower()
    markers = [
        label
        for pattern, label in _SUSPICIOUS_PATTERNS.items()
        if pattern in normalized_content
    ]
    return {
        "instruction_boundary": "data",
        "prompt_injection_risk": bool(markers),
        "suspicious_markers": tuple(markers),
        "source_basename": Path(locator).name,
    }
