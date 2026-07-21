"""Prompt-injection risk marking for untrusted web content.

Web content is always untrusted. This module annotates common injection
phrases so operators/evals can see them — it never deletes them, because
legitimate articles may discuss prompt injection (see Pipeline V2 §23.2).
The authoritative protection is the ``untrusted_external_content`` envelope
flag plus system rules that treat web text as data, not instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Lowercased markers. Matched case-insensitively as whole-word-ish substrings.
_INJECTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("ignore_previous_instructions", r"ignore (?:all )?previous instructions"),
    ("reveal_system_prompt", r"(?:reveal|show|print) (?:the )?system prompt"),
    ("run_command", r"run (?:this|the following) command"),
    ("exfiltrate_credentials", r"(?:upload|send|exfiltrate) (?:your )?credentials"),
    ("jailbreak_role", r"(?:you are now|act as) (?:dan|developer mode|root)"),
)

_COMPILED_MARKERS = tuple(
    (category, re.compile(pattern, re.IGNORECASE))
    for category, pattern in _INJECTION_MARKERS
)


@dataclass(frozen=True)
class ContentRiskAnnotation:
    marker_count: int
    categories: tuple[str, ...]

    @property
    def likely_injection_attempt(self) -> bool:
        return self.marker_count >= 2


def scan_for_injection_markers(text: str) -> ContentRiskAnnotation:
    """Scan ``text`` for common prompt-injection phrasing and return an
    annotation. Returns zero-count annotation for empty/blank text."""
    if not text:
        return ContentRiskAnnotation(marker_count=0, categories=())
    categories: list[str] = []
    for category, pattern in _COMPILED_MARKERS:
        if pattern.search(text):
            categories.append(category)
    return ContentRiskAnnotation(
        marker_count=len(categories),
        categories=tuple(categories),
    )
