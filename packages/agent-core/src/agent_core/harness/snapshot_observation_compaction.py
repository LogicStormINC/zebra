"""Reference identical snapshot characters already present in this model request."""

import json
from typing import Any
from uuid import UUID

from agent_core.domain.messages import MessageRole, SessionMessage

_CANDIDATES = "[Unverified word candidates; literal phrase not found]\n"
_EXCERPT = "\n\n[Next snapshot excerpt]\n\n"
_OMISSION = "\n\n[... middle omitted from model context ...]\n\n"
# start, end, original text, tool-call reference; no persistent or cross-request cache.
type _Source = tuple[int, int, str, str]


def compact_snapshot_observations(messages: list[SessionMessage]) -> list[SessionMessage]:
    seen: dict[str, list[_Source]] = {}
    invalid: set[str] = set()
    totals: dict[str, int] = {}
    retained = 0
    result = []
    for message in messages:
        if message.role is MessageRole.USER:
            seen.clear()
            invalid.clear()
            totals.clear()
            retained = 0
        parsed = _snapshot(message)
        if parsed is None:
            result.append(message)
            continue
        payload, uri, ranges, texts = parsed
        if uri in invalid:
            result.append(message)
            continue
        try:
            total = (payload.get("coverage") or payload["output_coverage"])["total_characters"]
            if uri in totals and totals[uri] != total:
                raise ValueError("same snapshot length changed")
            pieces = _pieces(ranges, texts, seen.get(uri, []))
        except ValueError:
            invalid.add(uri)
            seen.pop(uri, None)
            result.append(message)
            continue
        inline = [(a, b, text, message.tool_call_id or "") for a, b, text, ref in pieces
                  if ref is None]
        references = [{"range": [a, b], "tool_call_id": ref}
                      for a, b, _, ref in pieces if ref is not None]
        content = message.content
        # Fetch receipts seed the cache; only verified Artifact reads are rewritten.
        if references and isinstance(payload.get("coverage"), dict):
            coverage = dict(payload["coverage"])
            for key in ("included_start", "included_end", "included_ranges"):
                coverage.pop(key, None)
            coverage.update(included_ranges=[[a, b] for a, b, _, _ in inline],
                            referenced_ranges=references)
            rendered = "\n\n".join(
                f"[Snapshot range {a}:{b}]\n{text}" if ref is None else
                f"[Snapshot range {a}:{b} already in tool call {json.dumps(ref)}]"
                for a, b, text, ref in pieces
            )
            candidate = _CANDIDATES if payload["output"].startswith(_CANDIDATES) else ""
            changed = {**payload, "receipt_coverage": payload["coverage"],
                       "coverage": coverage,
                       "output": "[UNTRUSTED SNAPSHOT EXCERPTS]\n" + candidate + rendered}
            proposed = json.dumps(changed, ensure_ascii=False, sort_keys=True)
            if len(proposed) < len(content):
                content = proposed
        # ponytail: <=1MiB / 512 retained ranges per user turn; beyond this keep originals.
        # A larger budget/index is only warranted by measured large-context workloads.
        if retained + sum(len(text) for _, _, text, _ in inline) <= 1_048_576:
            previous = seen.setdefault(uri, [])
            if len(previous) + len(inline) <= 512:
                previous.extend(inline)
                previous.sort(key=lambda part: part[0])
                totals[uri] = total
                retained += sum(len(text) for _, _, text, _ in inline)
        result.append(message if content == message.content else message.model_copy(
            update={"content": content}
        ))
    return result


def _snapshot(
    message: SessionMessage,
) -> tuple[dict[str, Any], str, list[list[int]], list[str]] | None:
    if (message.role is not MessageRole.TOOL or len(message.content) > 262_144
            or message.metadata.get("tool_status") != "executed"):
        return None
    try:
        payload = json.loads(message.content)
        if not isinstance(payload, dict) or payload.get("status") != "executed":
            return None
        uri = message.metadata.get("artifact_uri")
        if not isinstance(uri, str) or uri != "artifact://" + str(UUID(uri[11:])):
            return None
        if payload.get("artifact_uri") != uri:
            return None
        coverage = message.metadata.get("coverage", message.metadata.get("output_coverage"))
        if not isinstance(coverage, dict):
            return None
        key = "coverage" if "coverage" in message.metadata else "output_coverage"
        if payload.get(key) != coverage:
            return None
        ranges = coverage.get("included_ranges")
        if ranges is None:
            ranges = [[coverage.get("included_start"), coverage.get("included_end")]]
        total = coverage.get("total_characters")
        if type(total) is not int or not isinstance(ranges, list) or not 1 <= len(ranges) <= 4:
            return None
        last = 0
        for pair in ranges:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(v) is not int for v in pair)
                    or not last <= pair[0] < pair[1] <= total):
                return None
            last = pair[1]
        output = payload.get("output")
        if not isinstance(output, str):
            return None
        if coverage.get("candidate_only") is True:
            if not output.startswith(_CANDIDATES):
                return None
            output = output[len(_CANDIDATES):]
        separator = _EXCERPT if key == "coverage" else _OMISSION
        texts = []
        for index, (a, b) in enumerate(ranges):
            if index:
                if not output.startswith(separator):
                    return None
                output = output[len(separator):]
            if len(output) < b - a:
                return None
            texts.append(output[:b - a])
            output = output[b - a:]
        if output and (key != "output_coverage" or output != f"\n\n[Complete output: {uri}]"):
            return None
        return payload, uri, ranges, texts
    except (ValueError, TypeError, RecursionError, AttributeError):
        return None


def _pieces(
    ranges: list[list[int]], texts: list[str], previous: list[_Source],
) -> list[tuple[int, int, str, str | None]]:
    pieces: list[tuple[int, int, str, str | None]] = []
    for (a, b), text in zip(ranges, texts, strict=True):
        cursor = a
        for c, d, old, reference in previous:
            start, end = max(a, c), min(b, d)
            if start >= end:
                continue
            if text[start - a:end - a] != old[start - c:end - c]:
                raise ValueError("same snapshot interval changed")
            if cursor < start:
                pieces.append((cursor, start, text[cursor - a:start - a], None))
            if cursor < end:
                pieces.append((max(cursor, start), end, "", reference))
            cursor = max(cursor, end)
        if cursor < b:
            pieces.append((cursor, b, text[cursor - a:], None))
    return pieces
