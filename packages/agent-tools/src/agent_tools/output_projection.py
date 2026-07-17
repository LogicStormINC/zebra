from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ProjectedToolOutput:
    model_output: str
    metadata: dict[str, object]


class ToolOutputProjector:
    def __init__(
        self,
        persist: Callable[[str, str], str],
        *,
        max_model_characters: int = 12_000,
    ) -> None:
        if max_model_characters < 256:
            raise ValueError("max_model_characters must be at least 256")
        self._persist = persist
        self._max_model_characters = max_model_characters

    def project(self, *, stdout: str, stderr: str, artifact_name: str) -> ProjectedToolOutput:
        complete = _complete_output(stdout, stderr)
        uri = self._persist(complete, artifact_name)
        encoded = complete.encode("utf-8")
        truncated = len(complete) > self._max_model_characters
        model_output = (
            _head_tail(complete, self._max_model_characters)
            if truncated
            else _small_model_output(stdout, stderr)
        )
        if truncated:
            model_output += f"\n\n[Complete output: {uri}]"
        return ProjectedToolOutput(
            model_output=model_output,
            metadata={
                "artifact_uri": uri,
                "output_sha256": sha256(encoded).hexdigest(),
                "output_size_bytes": len(encoded),
                "output_truncated": truncated,
            },
        )


def _complete_output(stdout: str, stderr: str) -> str:
    sections = []
    if stdout:
        sections.append(f"[stdout]\n{stdout}")
    if stderr:
        sections.append(f"[stderr]\n{stderr}")
    return "\n\n".join(sections) or "[no output]"


def _small_model_output(stdout: str, stderr: str) -> str:
    if stdout and not stderr:
        return stdout
    if stderr and not stdout:
        return f"[stderr]\n{stderr}"
    return _complete_output(stdout, stderr)


def _head_tail(value: str, limit: int) -> str:
    marker = "\n\n[... middle omitted from model context ...]\n\n"
    available = limit - len(marker)
    head = available // 2
    return value[:head] + marker + value[-(available - head) :]
