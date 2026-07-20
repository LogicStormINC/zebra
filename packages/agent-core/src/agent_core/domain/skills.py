from __future__ import annotations

import re
from collections.abc import Sequence

MAX_SKILL_COMPONENTS = 32
_SKILL_COMPONENT_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


def normalize_skill_components(value: Sequence[str]) -> tuple[str, ...]:
    if len(value) > MAX_SKILL_COMPONENTS:
        raise ValueError(f"skill_components accepts at most {MAX_SKILL_COMPONENTS} entries")
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not _SKILL_COMPONENT_NAME.fullmatch(entry):
            raise ValueError(
                "skill_components entries must match ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"
            )
        if entry in seen:
            raise ValueError("skill_components entries must be unique")
        seen.add(entry)
        normalized.append(entry)
    return tuple(sorted(normalized))
