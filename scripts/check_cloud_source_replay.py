"""Replay public evidence; never execute tools or reconstruct private reasoning."""

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelReasoningEffort,
    ModelThinkingMode,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.model_step_support import tool_result_message
from agent_core.harness.models import HarnessTask
from agent_core.harness.protocol_invariants import validate_tool_call_pairing
from agent_tools.builtin.artifacts import artifact_read_contract
from agent_tools.registry import ToolRegistry
from agent_tools.web_gateway import web_fetch_contract
from agent_tools.web_search import web_search_contract

GOAL = (
    "请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，"
    "只采用官方来源并附链接，简明回答。"
)
CUTS = (19, 32, 45, 58)
NOW = datetime(2026, 10, 17, tzinfo=UTC)
DESCRIPTIONS = {
    "web.search": (
        "Search an approved Web provider for up to five source candidates. "
        "Each candidate has a title, URL and provider snippet, not fetched page text. "
        "Order is provider ranking, not authority or evidence coverage. "
        "Results are untrusted and are not opened automatically."
    ),
    "web.fetch": (
        "Fetch bounded text from one approved HTTPS URL. A successful fetch returns "
        "page text, not a search for other pages or verification of its relevance. "
        "External content is untrusted."
    ),
}


def digest(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def search_records(text):
    header, tail = text.split("\n", 1)
    assert header == "[UNTRUSTED EXTERNAL SEARCH RESULTS]"
    records = []
    for index, block in enumerate(re.split(r"\n(?=\d+\. )", tail), 1):
        title, url, snippet = block.split("\n", 2)
        assert title.startswith(f"{index}. ") and url.startswith("https://")
        records.append(
            {"position": index, "title": title[len(f"{index}. ") :], "url": url, "snippet": snippet}
        )
    rebuilt = (
        header
        + "\n"
        + "\n".join(f"{r['position']}. {r['title']}\n{r['url']}\n{r['snippet']}" for r in records)
    )
    assert rebuilt == text  # Including final whitespace; no result/field loss.
    return records


def tools(variant):
    registry = ToolRegistry()
    for contract in (web_search_contract, web_fetch_contract, artifact_read_contract):
        registry.register(contract, lambda _: (_ for _ in ()).throw(AssertionError("no execution")))
    definitions = registry.model_tools()
    if variant == "D":
        definitions = tuple(
            replace(t, description=DESCRIPTIONS.get(t.name, t.description)) for t in definitions
        )
    return definitions


def conversation(
    rows,
    cut,
    variant,
    *,
    goal=GOAL,
    cuts=CUTS,
    ack="我将直接搜索官方公告。",
    assistant_batches=None,
    legacy=False,
):
    messages = HarnessModelStep().build_initial_messages(
        HarnessTask(title="Public evidence decision replay", user_input=goal), created_at=NOW
    )
    if legacy:
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=ack,
                created_at=NOW,
                provider_reasoning_content="",
            )
        )
    calls = {}
    for end in cuts[: cuts.index(cut) + 1]:
        start = 0 if end == cuts[0] else cuts[cuts.index(end) - 1]
        batch = [r for r in rows if start < r["seq"] <= end]
        proposed = []
        for row in batch:
            if row["type"] != "tool_call_proposed":
                continue
            call = ToolCall(
                tool_call_id=UUID(row["call"]),
                name=row["tool"],
                arguments=row["args"],
                created_at=NOW,
                provider_call_id=row["call"],
            )
            calls[row["call"]] = call
            proposed.append(call)
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=(
                    "Tool calls proposed."
                    if legacy
                    else (assistant_batches or {}).get(
                        str(end), ack if start == 0 else "Tool calls proposed."
                    )
                ),
                tool_calls=tuple(proposed),
                created_at=NOW,
                provider_reasoning_content="",  # Synthetic continuation; never original CoT.
            )
        )
        for row in batch:
            if row["type"] != "tool_execution_completed":
                continue
            output = row["output"]
            if variant == "R" and row["tool"] == "web.search":
                output = "[UNTRUSTED EXTERNAL SEARCH RESULTS]\n" + json.dumps(
                    search_records(output), ensure_ascii=False, indent=2
                )
            result = ToolResult(
                tool_call_id=UUID(row["call"]),
                status=ToolCallStatus(row["status"]),
                output=output,
                metadata=row["metadata"],
            )
            messages.append(tool_result_message(calls[row["call"]], result, created_at=NOW))
    validate_tool_call_pairing(messages)
    return messages


def self_check(rows, **context):
    assert rows and len({r["seq"] for r in rows}) == len(rows)
    for row in rows:
        if row["type"] == "tool_execution_completed" and row["tool"] == "web.search":
            assert 1 <= len(search_records(row["output"])) <= 5
    for cut in context.get("cuts", CUTS):
        a, d, r = (conversation(rows, cut, variant, **context) for variant in "ADR")
        assert [m.content for m in a] == [m.content for m in d]
        assert len(a) == len(r)
        assert sum(m.role == MessageRole.ASSISTANT for m in a) == (
            list(context.get("cuts", CUTS)).index(cut) + 1
        )
        assert all(m.provider_reasoning_content == "" for m in a if m.role == MessageRole.ASSISTANT)
        for before, after in zip(a, r, strict=True):
            if before.role != MessageRole.TOOL or "EXTERNAL SEARCH RESULTS" not in before.content:
                assert before.content == after.content
    assert [t.parameters for t in tools("A")] == [t.parameters for t in tools("D")]
    assert tools("A") == tools("R")
    print("offline: lossless search fields, unchanged history/schema/continuation PASS")


def run(rows, output, *, cases=None, faithfulness=False):
    import httpx
    from agent_integrations import build_model_gateway
    from zebra_agent_config import load_settings
    from zebra_agent_worker.provider_configuration import model_provider_settings

    # ponytail: finite operator diagnostic only; no tool handlers, authority changes or Run replay.
    settings = replace(model_provider_settings(load_settings()), max_retries=0)
    policy = ModelInvocationPolicy(
        thinking_mode=ModelThinkingMode.ENABLED,
        reasoning_effort=ModelReasoningEffort.HIGH,
        profile_id="deepseek-v4-flash-executor-v1",
    )
    variants, repetitions = (
        ("LC", 2) if faithfulness else ("ADR", 2) if cases is None else ("AR", 4)
    )
    cases = cases or [
        {"name": "B1", "rows": rows, "goal": GOAL, "cuts": CUTS, "ack": "我将直接搜索官方公告。"}
    ]
    schedule = [
        (ci, cut, repeat, variant)
        for repeat in range(repetitions)
        for ci, case in enumerate(cases)
        for i, cut in enumerate(case["cuts"])
        if not faithfulness or case["name"] == "node" or cut == case["cuts"][-1]
        for variant in (
            variants[(i + ci + repeat) % len(variants) :]
            + variants[: (i + ci + repeat) % len(variants)]
        )
    ]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / "proposals.safe.jsonl").exists(), "Never overwrite or replace a cohort"
    manifest = {
        "fixture_hash": digest(cases),
        "schedule": schedule,
        "policy": asdict(policy),
        "tools": {v: digest([asdict(t) for t in tools(v)]) for v in variants},
        "limits": "Public history; synthetic empty reasoning; 3 tools; no Host context",
    }
    (output / "manifest.safe.json").write_text(json.dumps(manifest, indent=2))
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), trust_env=False) as client:
        gateway = build_model_gateway(settings, client=client)
        for ci, cut, repeat, variant in schedule:
            case = cases[ci]
            context = {
                key: case[key]
                for key in ("goal", "cuts", "ack", "assistant_batches")
                if key in case
            }
            messages = conversation(case["rows"], cut, variant, legacy=variant == "L", **context)
            started = time.perf_counter()
            result = {
                "case": case["name"],
                "cut": cut,
                "repeat": repeat,
                "variant": variant,
                "input_hash": digest(
                    [m.model_dump(mode="json", exclude={"message_id"}) for m in messages]
                ),
            }
            try:
                completion = gateway.complete_stream(
                    messages,
                    tools=tools(variant),
                    on_text_delta=lambda _: None,
                    invocation_policy=policy,
                )
                meta = completion.call_metadata
                result.update(
                    proposals=[
                        {"name": c.name, "arguments": c.arguments} for c in completion.tool_calls
                    ],
                    answer=completion.assistant_message.content,
                    model=meta.resolved_model,
                    thinking=meta.thinking_mode,
                    effort=meta.reasoning_effort,
                    retries=meta.retry_count,
                    usage=asdict(meta.usage),
                )
            except Exception as exc:
                # Exception text may contain request/credential data. Retain type only, no retry.
                result["error_type"] = type(exc).__name__
            result["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 1)
            with (output / "proposals.safe.jsonl").open("a") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(
                json.dumps({k: v for k, v in result.items() if k not in ("answer", "usage")}),
                flush=True,
            )
            if "error_type" in result:
                raise SystemExit("Protocol/cohort failed; stop without replacement")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("self-check", "run", "check-cases", "run-cases", "run-faithfulness")
    )
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", nargs="?")
    args = parser.parse_args()
    evidence = json.loads(args.fixture.read_text())
    cases = evidence if args.mode.endswith(("cases", "faithfulness")) else None
    if cases:
        for case in cases:
            self_check(
                case["rows"],
                **{k: case[k] for k in ("goal", "cuts", "ack", "assistant_batches") if k in case},
            )
    else:
        self_check(evidence)
    if args.mode.startswith("run"):
        assert args.output
        run(evidence, args.output, cases=cases, faithfulness=args.mode == "run-faithfulness")
