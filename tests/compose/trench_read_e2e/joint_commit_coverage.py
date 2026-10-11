"""QA-only canonical source-plan coverage, independent of Host frame classification."""

from typing import Any

from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType
from agent_core.harness.model_commentary import commentary_outputs, text_hash


class CommentaryCoverage:
    def __init__(self) -> None:
        self.sources: list[dict[str, Any]] = []
        self.expected: dict[str, dict[str, Any]] = {}
        self.published: set[str] = set()
        self.invalids: list[str] = []

    def observe(self, entry: Any) -> None:
        event = entry.event
        if event.event_type not in (EventType.MODEL_RESPONSE_RECEIVED, EventType.PUBLIC_OUTPUT):
            return
        payload = event.payload
        try:
            if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
                text = payload.get("assistant_message")
                raw = payload.get("public_commentary")
                if raw is None:
                    if (
                        payload.get("response_stage") == "tool_loop"
                        and isinstance(text, str)
                        and text.strip()
                        and text.strip() != "Tool calls proposed."
                    ):
                        self.invalids.append("legacy_model_commentary_has_no_canonical_plan")
                    return
                drafts = commentary_outputs(payload)
                self.sources.append(
                    {
                        "event_id": str(event.event_id),
                        "task_sequence": entry.task_sequence,
                        "disposition": raw["disposition"],
                        "output_ids": raw["output_ids"],
                        "source_sha256": raw["source_sha256"],
                    }
                )
                if raw["disposition"] != "admitted":
                    self.invalids.append("source_commentary_" + raw["disposition"])
                for draft in drafts:
                    key = str(draft.payload["output_id"])
                    if key in self.expected:
                        raise ValueError("duplicate_source_plan")
                    self.expected[key] = {
                        **draft.payload,
                        "content": text_hash(str(draft.payload["content"])),
                    }
            elif payload.get("phase") == "model_commentary":
                output = PublicOutputPayload.model_validate(payload)
                key = output.output_id
                if key not in self.expected or key in self.published:
                    raise ValueError("unplanned_or_duplicate_chunk")
                expected = self.expected[key]
                actual = {**payload, "content": text_hash(output.content)}
                if any(actual.get(field) != value for field, value in expected.items()):
                    raise ValueError("source_chunk_mismatch")
                self.published.add(key)
        except Exception:
            self.invalids.append("invalid_canonical_commentary_plan_or_chunk")

    def report(self) -> dict[str, Any]:
        missing = sorted(set(self.expected) - self.published)
        return {
            "schema_version": 1,
            "source_plans": self.sources,
            "published_output_ids": sorted(self.published),
            "missing_output_ids": missing,
            "invalids": self.invalids,
            "complete": not missing and not self.invalids,
        }


def require_commentary_coverage(native: dict[str, Any]) -> None:
    coverage = native.get("commentary_coverage")
    if coverage is None:
        return  # Old probe evidence retains its existing strict frame/paint validation.
    if (
        coverage.get("complete") is not True
        or coverage.get("invalids")
        or coverage.get("missing_output_ids")
        or coverage.get("schema_version") != 1
    ):
        raise ValueError("commentary_coverage_incomplete")
    sources = coverage["source_plans"]
    expected = [key for source in sources for key in source["output_ids"]]
    if (
        any(source["disposition"] != "admitted" for source in sources)
        or len(set(expected)) != len(expected)
        or set(expected) != set(coverage["published_output_ids"])
    ):
        raise ValueError("commentary_source_plan_incomplete")
    actual = {
        row.get("output_id") for row in native["records"] if row["event_type"] == "public_output"
    }
    if not set(expected).issubset(actual):
        raise ValueError("planned_commentary_missing_native_visibility")
