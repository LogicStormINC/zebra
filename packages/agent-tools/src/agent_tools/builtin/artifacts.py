import heapq
import re
from collections.abc import Iterator
from itertools import chain

from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports import ArtifactPayloadReadPort

from agent_tools.contracts import ToolContract
from agent_tools.errors import ToolArgumentError

artifact_read_contract = ToolContract(
    name="artifacts.read",
    parallel_safe=True,
    required_arguments=("uri",),
    description=(
        "Read a bounded segment from an authorized Artifact snapshot in this session. "
        "Use query for bounded literal excerpts or unverified same-snapshot word candidates, "
        "scanning a long document by offsets. Coverage uses original character offsets."
    ),
    argument_properties={
        "uri": {"type": "string", "description": "Canonical artifact:// URI."},
        "offset": {"type": "integer", "minimum": 0},
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "description": (
                "Optional case-insensitive literal phrase, not a regular expression. "
                "Returns up to four short excerpts at or after offset, sharing max_characters. "
                "No literal match may return word-overlap candidates, explicitly unverified. "
                "next_cursor continues literal matches; candidates do not establish facts."
            ),
        },
        "max_characters": {
            "type": "integer",
            "minimum": 1,
            "maximum": 16000,
            "description": "Total returned text budget, including warning and separators.",
        },
    },
)


class ArtifactReadTool:
    def __init__(self, reader: ArtifactPayloadReadPort, session_id: SessionId) -> None:
        self._reader = reader
        self._session_id = session_id

    @property
    def contract(self) -> ToolContract:
        return artifact_read_contract

    def handle(self, tool_call: ToolCall) -> ToolResult:
        uri = tool_call.arguments.get("uri")
        offset = tool_call.arguments.get("offset", 0)
        limit = tool_call.arguments.get("max_characters", 8_192)
        query = tool_call.arguments.get("query")
        if not isinstance(uri, str) or not uri.strip():
            raise ToolArgumentError("artifacts.read requires a non-blank uri")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ToolArgumentError("artifacts.read offset must be a non-negative integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 16_000:
            raise ToolArgumentError("artifacts.read max_characters must be between 1 and 16000")
        if "query" in tool_call.arguments and (
            not isinstance(query, str) or not query.strip() or len(query) > 256
        ):
            raise ToolArgumentError(
                "artifacts.read query must be a nonblank literal up to 256 characters"
            )
        if isinstance(query, str) and len(query) > limit:
            raise ToolArgumentError("artifacts.read max_characters must fit the complete query")
        try:
            complete = self._reader.read_payload_bytes(self._session_id, uri.strip()).decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "artifact_unavailable", "detail": str(exc)[:1000]},
            )
        offset = min(offset, len(complete))
        if isinstance(query, str):
            output, coverage, cursor = _query_excerpts(complete, query, offset, limit)
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.EXECUTED,
                output=output,
                metadata={
                    "artifact_uri": uri.strip(),
                    "coverage": coverage,
                    "truncated": cursor is not None,
                    "has_more": cursor is not None,
                    "next_cursor": cursor,
                },
            )
        start = offset
        visible = complete[start : start + limit]
        end = start + len(visible)
        more = end < len(complete)
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=visible or "[no content in requested range]",
            metadata={
                "artifact_uri": uri.strip(),
                "coverage": {
                    "included_start": start,
                    "included_end": end,
                    "total_characters": len(complete),
                },
                "truncated": more,
                "has_more": more,
                "next_cursor": end if more else None,
            },
        )


def _query_excerpts(
    text: str,
    query: str,
    offset: int,
    limit: int,
) -> tuple[str, dict[str, object], int | None]:
    matches = re.compile(re.escape(query), re.IGNORECASE).finditer(text, offset)
    first = next(matches, None)
    literal = first is not None
    anchors = (
        ((m.start(), m.end()) for m in chain((first,), matches))
        if first is not None
        else iter(_term_candidates(text, query, offset))
    )
    # ponytail: four bounded windows, no index or semantic inference; snapshot stays unchanged.
    output = "" if literal else "[Unverified word candidates; literal phrase not found]\n"
    if not literal and len(output) >= limit:
        output = ""
        anchors = iter(())
    ranges: list[list[int]] = []
    hits: list[dict[str, object]] = []
    cursor = None
    for match_start, match_end in anchors:
        if any(start <= match_start < end for start, end in ranges):
            continue
        separator = "\n\n[Next snapshot excerpt]\n\n" if ranges else ""
        kind = _excerpt_kind(text, match_start)
        room = min(
            512 if kind != "text" else (2_048 if literal else 1_024),
            limit - len(output) - len(separator),
        )
        if len(ranges) == 4 or room < match_end - match_start:
            cursor = match_start if literal else None
            break
        before = min(128, (room - (match_end - match_start)) // 3)
        start = max(offset, match_start - before)
        if literal and ranges:
            start = max(start, ranges[-1][1])
        end = min(len(text), start + room)
        if not literal and any(start < b and end > a for a, b in ranges):
            continue
        output += separator + text[start:end]
        ranges.append([start, end])
        hits.append({"start": match_start, "end": match_end, "kind": kind})
    if not ranges:
        output = ""
    coverage: dict[str, object] = {
        "total_characters": len(text),
        "search_start": offset,
        "literal_match": literal,
        "candidate_only": not literal,
        "candidate_selection_exhaustive": False,
        "included_ranges": ranges,
        "matches": hits,
    }
    return output, coverage, cursor


def _term_candidates(text: str, query: str, offset: int) -> list[tuple[int, int]]:
    # ponytail: bounded word overlap only; no stemming, synonyms or semantic completeness.
    terms = set(
        list(dict.fromkeys(term.casefold() for term in re.findall(r"\w+", query) if len(term) > 1))[
            :16
        ]
    )
    if not terms:
        return []

    def paragraphs() -> Iterator[tuple[int, int, int]]:
        for paragraph in re.finditer(r"\S[^\n]*(?:\n[^\n]+)*", text[offset:]):
            shared: set[str] = set()
            anchor = None
            for word in re.finditer(r"\w+", paragraph.group()):
                term = word.group().casefold()
                if term in terms:
                    shared.add(term)
                    if anchor is None:
                        base = offset + paragraph.start()
                        anchor = (base + word.start(), base + word.end())
            if anchor is not None:
                yield len(shared), *anchor

    ranked = heapq.nlargest(4, paragraphs(), key=lambda item: (item[0], -item[1]))
    return [(start, end) for _, start, end in ranked]


def _excerpt_kind(text: str, position: int) -> str:
    fence = ""
    kind = "text"
    for line in text[:position].splitlines():
        match = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if match is None:
            continue
        marker, label = match.groups()
        if fence:
            if marker[0] == fence[0] and len(marker) >= len(fence) and not label.strip():
                fence, kind = "", "text"
        else:
            fence = marker
            kind = "fenced_metadata" if re.search(r"\bmetadata\b", label, re.I) else "fenced_code"
    return kind
