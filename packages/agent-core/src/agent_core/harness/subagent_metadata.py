from agent_core.domain.tools import ToolResult


def aggregate_subagent_metadata(
    metadata: dict[str, object],
    tool_result: ToolResult,
) -> dict[str, object]:
    child_id = tool_result.metadata.get("subagent_id")
    if not isinstance(child_id, str) or not child_id:
        return metadata
    raw_status = tool_result.metadata.get("subagent_status")
    status = raw_status if raw_status in {"completed", "failed", "cancelled"} else "failed"
    identifiers = [*_string_list(metadata.get("subagent_ids")), child_id]
    return {
        **metadata,
        "subagent_ids": identifiers,
        "subagent_count": len(identifiers),
        "subagent_model_calls_used": _summed_metric(
            metadata,
            tool_result,
            aggregate_key="subagent_model_calls_used",
            result_key="model_calls_used",
        ),
        "subagent_tool_calls_used": _summed_metric(
            metadata,
            tool_result,
            aggregate_key="subagent_tool_calls_used",
            result_key="tool_calls_used",
        ),
        "subagent_source_count": _summed_metric(
            metadata,
            tool_result,
            aggregate_key="subagent_source_count",
            result_key="source_count",
        ),
        f"subagent_{status}_count": _metric(metadata, f"subagent_{status}_count") + 1,
    }


def _summed_metric(
    metadata: dict[str, object],
    tool_result: ToolResult,
    *,
    aggregate_key: str,
    result_key: str,
) -> int:
    return _metric(metadata, aggregate_key) + _metric(tool_result.metadata, result_key)


def _metric(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
