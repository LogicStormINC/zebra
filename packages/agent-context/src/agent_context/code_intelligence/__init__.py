"""Optional bounded code intelligence index (ARCH-129-CTX-01).

A non-authoritative, purely lexical symbol index over a workspace tree:
definitions and references with file/range provenance, explicit ceilings,
deterministic truncation, and a staleness digest. It never grants capability
or authority; callers treat results as hints and the workspace tree stays the
only source of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_FILES = 2_000
DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_RESULTS = 200

_SYMBOL_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)(?:async\s+)?(?:def|class|function|func|fn|struct|impl|type)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_REFERENCE_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass(frozen=True)
class SymbolRange:
    file: str
    line: int
    column: int

    def to_payload(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "column": self.column}


@dataclass(frozen=True)
class SymbolDefinition:
    name: str
    range: SymbolRange
    kind: str
    truncated: bool = False


@dataclass(frozen=True)
class SymbolReference:
    name: str
    range: SymbolRange


@dataclass
class CodeIntelligenceIndex:
    """Bounded lexical symbol index; deterministic and process-free."""

    root: Path
    max_files: int = DEFAULT_MAX_FILES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_results: int = DEFAULT_MAX_RESULTS
    _definitions: dict[str, list[SymbolDefinition]] = field(default_factory=dict)
    _files_indexed: int = 0
    _files_skipped: int = 0
    _truncated_files: int = 0

    def build(self) -> CodeIntelligenceIndex:
        if not self.root.is_dir():
            raise ValueError("code intelligence root must be a directory")
        for path in sorted(self.root.rglob("*")):
            if self._files_indexed >= self.max_files:
                break
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                self._files_skipped += 1
                continue
            if size > self.max_file_bytes:
                self._files_skipped += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                self._files_skipped += 1
                continue
            truncated = size == self.max_file_bytes
            if truncated:
                self._truncated_files += 1
            self._index_file(path, text, truncated)
            self._files_indexed += 1
        return self

    def _index_file(self, path: Path, text: str, truncated: bool) -> None:
        relative = str(path.relative_to(self.root))
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _SYMBOL_PATTERN.match(line)
            if match is None:
                continue
            name = match.group("name")
            kind = _classify(match.group(0))
            definition = SymbolDefinition(
                name=name,
                range=SymbolRange(
                    file=relative,
                    line=line_number,
                    column=len(match.group("indent")) + 1,
                ),
                kind=kind,
                truncated=truncated,
            )
            self._definitions.setdefault(name, []).append(definition)

    def definitions(self, name: str) -> list[SymbolDefinition]:
        return list(self._definitions.get(name, ()))[: self.max_results]

    def search(self, prefix: str) -> list[SymbolDefinition]:
        matches: list[SymbolDefinition] = []
        for symbol in sorted(self._definitions):
            if symbol.startswith(prefix):
                matches.extend(self._definitions[symbol])
                if len(matches) >= self.max_results:
                    return matches[: self.max_results]
        return matches

    def references(self, name: str, *, max_lines: int = 20_000) -> list[SymbolReference]:
        """Bounded lexical reference scan; hints only, never authoritative."""
        pattern = _REFERENCE_PATTERN_CACHE.get(name)
        if pattern is None:
            pattern = re.compile(rf"\b{re.escape(name)}\b")
            _REFERENCE_PATTERN_CACHE[name] = pattern
        results: list[SymbolReference] = []
        lines_scanned = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if lines_scanned >= max_lines or len(results) >= self.max_results:
                break
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                continue
            relative = str(path.relative_to(self.root))
            for line_number, line in enumerate(text.splitlines(), start=1):
                lines_scanned += 1
                if lines_scanned > max_lines:
                    break
                column = line.find(name)
                if column >= 0 and pattern.search(line):
                    results.append(
                        SymbolReference(
                            name=name,
                            range=SymbolRange(
                                file=relative, line=line_number, column=column + 1
                            ),
                        )
                    )
                    if len(results) >= self.max_results:
                        return results
        return results

    def stats(self) -> dict[str, int]:
        return {
            "files_indexed": self._files_indexed,
            "files_skipped": self._files_skipped,
            "truncated_files": self._truncated_files,
            "symbols": len(self._definitions),
            "max_files": self.max_files,
            "max_results": self.max_results,
        }


def _classify(declaration: str) -> str:
    stripped = declaration.strip()
    if stripped.startswith("class") or stripped.startswith("struct"):
        return "type"
    if stripped.startswith("type") or stripped.startswith("impl"):
        return "type"
    return "function"
