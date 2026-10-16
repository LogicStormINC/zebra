"""uv run python scripts/check_search_suspension.py; no framework, model or network."""

import json

from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.harness.model_step_support import tool_result_content
from agent_core.harness.tool_recovery import normalize_failure
from agent_runtime.search_health import require_complete_search
from agent_tools.web_gateway import WebGatewayError


def observe(payload):
    try:
        require_complete_search(payload)
    except WebGatewayError as error:
        result = ToolResult(
            tool_call_id=new_tool_call_id(), status=ToolCallStatus.FAILED,
            metadata={**error.metadata, "reason": error.reason, "detail": str(error)},
        )
        return normalize_failure(result, read_only=True)
    raise AssertionError("incomplete source accepted")


def check():
    paused = observe({"results": [], "unresponsive_engines": [["yahoo", "Suspended: timeout"]]})
    assert paused.metadata["execution_state"] == "not_executed"
    assert paused.metadata["retryable"] is False
    assert "retry_after_seconds" not in paused.metadata
    view = json.loads(tool_result_content(paused))
    assert "suspended" in view["detail"]
    assert "Changing query text" in view["recovery_hint"]
    assert "Correct the arguments" not in view["recovery_hint"]
    timeout = observe({"results": [], "unresponsive_engines": [["yahoo", "timeout"]]})
    assert timeout.metadata["execution_state"] == "executed"
    assert timeout.metadata["retryable"] is True
    assert timeout.metadata["retry_after_seconds"] == 5
    for payload in (
        {"results": [{"url": "https://source.test/a"}],
         "unresponsive_engines": [["yahoo", "Suspended: timeout"]]},
        {"results": [], "unresponsive_engines": [["yahoo", "Suspended: timeout"],
                                                  ["other", "timeout"]]},
        {"results": [], "unresponsive_engines": [["yahoo", "Suspended: timeout"]] * 9},
    ):
        result = observe(payload)
        assert result.metadata["execution_state"] != "not_executed"
        assert not result.metadata.get("evidence_refs")
    for failure in ("CAPTCHA", "Suspended: CAPTCHA", "access denied", "429"):
        result = observe({"results": [], "unresponsive_engines": [["yahoo", failure]]})
        assert result.metadata["retryable"] is False
    require_complete_search({"results": [], "unresponsive_engines": []})
    write = normalize_failure(ToolResult(
        tool_call_id=new_tool_call_id(), status=ToolCallStatus.FAILED,
        metadata={"category": "upstream_search", "execution_state": "unknown"},
    ), read_only=False)
    assert "Do not repeat this write" in write.metadata["recovery_hint"]
    print("paused state, timeout, mixed/partial bounds, model view and write safety pass")


if __name__ == "__main__":
    check()
