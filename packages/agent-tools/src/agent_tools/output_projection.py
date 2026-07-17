from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256


@dataclass(frozen=True)
class ProjectedToolOutput:
    model_output: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class ToolOutputEnvelope:
    content_type: str
    preview_head: str
    preview_tail: str
    digest: str
    artifact_uri: str
    original_bytes: int
    retained_bytes: int
    truncated: bool
    checksum: str
    provenance: dict[str, object]

    def to_metadata(self) -> dict[str, object]:
        return asdict(self)


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

    def project(
        self,
        *,
        stdout: str,
        stderr: str,
        artifact_name: str,
        provenance: Mapping[str, object] | None = None,
    ) -> ProjectedToolOutput:
        source = dict(provenance or {})
        source["streams"] = [
            name
            for name, value in (("stdout", stdout), ("stderr", stderr))
            if value
        ]
        return self.project_text(
            _complete_output(stdout, stderr),
            artifact_name=artifact_name,
            small_output=_small_model_output(stdout, stderr),
            provenance=source,
        )

    def project_text(
        self,
        content: str,
        *,
        artifact_name: str,
        content_type: str = "text/plain",
        provenance: Mapping[str, object] | None = None,
        small_output: str | None = None,
    ) -> ProjectedToolOutput:
        if not content_type.strip():
            raise ValueError("content_type must not be blank")
        complete = content or "[no output]"
        uri = self._persist(complete, artifact_name)
        encoded = complete.encode("utf-8")
        truncated = len(complete) > self._max_model_characters
        head, tail = _preview_parts(complete, self._max_model_characters)
        model_output = _head_tail(complete, self._max_model_characters) if truncated else (
            complete if small_output is None else small_output
        )
        if truncated:
            model_output += f"\n\n[Complete output: {uri}]"
        checksum = sha256(encoded).hexdigest()
        envelope = ToolOutputEnvelope(
            content_type=content_type,
            preview_head=head,
            preview_tail=tail,
            digest=f"sha256:{checksum}",
            artifact_uri=uri,
            original_bytes=len(encoded),
            retained_bytes=len(encoded),
            truncated=truncated,
            checksum=checksum,
            provenance=dict(provenance or {}),
        )
        return ProjectedToolOutput(
            model_output=model_output,
            metadata={
                "artifact_uri": uri,
                "output_sha256": checksum,
                "output_size_bytes": len(encoded),
                "output_truncated": truncated,
                "output_envelope": envelope.to_metadata(),
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


def _preview_parts(value: str, limit: int) -> tuple[str, str]:
    if len(value) <= limit:
        return value, ""
    half = limit // 2
    return value[:half], value[-(limit - half) :]
