"""Real media executors; synthetic business rows are never provider/receipt evidence."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from isolation import joint_preflight
from joint_acceptance import native_source_identity, validate_live_evidence
from joint_business_seed import seed_business, validate_seed
from scratch_topology import docker
from support import Config, E2EError, task_binding

MEDIA_CASES = frozenset({"image", "inline_video", "chart_markdown_latex", "revision"})
GOOD_CHART = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"values": [{"source": "A", "growth": 12}, {"source": "B", "growth": 8}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "source", "type": "nominal"},
        "y": {"field": "growth", "type": "quantitative"},
    },
}
BAD_CHART = {**GOOD_CHART, "mark": "qa-invalid-mark"}

# This writes entitled business media URLs only, inside the pinned scratch Host.
# It does not insert Zebra Events, tool receipts, model responses or frontend parts.
MEDIA_SEED = """
import asyncio,json,os,re,sys
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from trench_core.orm.event import EventRow
from trench_core.orm.trench_ai_subscription_period import TrenchAiSubscriptionPeriodRow
data=json.loads(sys.stdin.read(16384));scope=data['namespace_id']
assert re.fullmatch(r'zebra-progress-e2e-qa-[a-f0-9]{12}',scope)
assert os.environ['ZEBRA_CLIENT_NAMESPACE_ID']==scope
assert os.environ['DATABASE_URL'].endswith('/'+scope+'_trench')
url=os.environ['DATABASE_URL'].replace('postgresql://','postgresql+asyncpg://',1)
engine=create_async_engine(url,connect_args={'timeout':2,'command_timeout':2})
async def update():
 async with asyncio.timeout(8):
  async with async_sessionmaker(engine)() as session,session.begin():
   event=await session.get(EventRow,data['event_id'])
   period=await session.get(TrenchAiSubscriptionPeriodRow,data['period_id'])
   assert event is not None and period is not None
   assert period.source_id==event.source_id and period.user_id==data['user_id']
   assert period.workspace_id==data['workspace_id'] and period.ended_at is None
   event.images_json=json.dumps([data['image_url'],data['image_url']])
   event.videos_json=json.dumps([data['video_url']])
   event.original_url=data['video_url']
   event.content_text='QA media evidence. Independent source A=12%, B=8%.'
   await session.flush()
 await engine.dispose()
 print(json.dumps({'event_id':data['event_id'],'period_id':data['period_id'],
   'image_url':data['image_url'],'video_url':data['video_url'],
   'scope':'actual_scratch_business_rows','provider_or_receipt_injection':False}))
asyncio.run(update())
"""


def validate_media_fixture(fixture: Mapping[str, Any]) -> None:
    if (
        fixture.get("scope") != "actual_scratch_business_rows"
        or fixture.get("provider_or_receipt_injection") is not False
        or not re.fullmatch(r"[a-f0-9]{32}", str(fixture.get("event_id", "")))
        or not re.fullmatch(r"qa-period-[a-f0-9]{32}", str(fixture.get("period_id", "")))
    ):
        raise E2EError("media_business_fixture_unproven")
    for key in ("image_url", "video_url"):
        value = fixture.get(key)
        if not isinstance(value, str) or len(value) > 2048:
            raise E2EError("media_source_url_invalid")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in (None, 443)
            or not re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", parsed.hostname)
            or parsed.hostname.endswith((".localhost", ".internal", ".local"))
            or (key == "video_url" and not parsed.path.lower().endswith((".mp4", ".webm")))
        ):
            raise E2EError("media_source_url_invalid")


def seed_media(config: Config, *, image_url: str, video_url: str) -> dict[str, Any]:
    # Validate before any native write, then reuse the existing guarded row seed.
    candidate = {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "event_id": "0" * 32,
        "period_id": "qa-period-" + "0" * 32,
        "image_url": image_url,
        "video_url": video_url,
    }
    validate_media_fixture(candidate)
    seed = seed_business(config)
    validate_seed(seed)
    proof = joint_preflight(config)
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    payload = {
        **candidate,
        "event_id": seed["event_ids"][0],
        "period_id": "qa-period-" + seed["source_ids"][0],
        "namespace_id": proof["namespace_id"],
        "user_id": config.user_id,
        "workspace_id": config.workspace_id,
    }
    output = docker(
        ["exec", "-i", manifest["containers"]["trench_api"]["id"], "python", "-c", MEDIA_SEED],
        input_text=json.dumps(payload),
        timeout=10,
    )
    if len(output.encode()) > 16384:
        raise E2EError("media_seed_evidence_oversized")
    fixture: dict[str, Any] = json.loads(output)
    validate_media_fixture(fixture)
    return fixture


def media_prompt(case_id: str, marker: str, fixture: Mapping[str, Any]) -> str:
    validate_media_fixture(fixture)
    if case_id not in MEDIA_CASES:
        raise E2EError("media_case_executor_unimplemented")
    instructions = {
        "image": (
            "这是媒体故障隔离验收。通过 media.import_historical 分别导入 image 索引1和2，"
            "每个独立调用 content.present，alt 分别为 QA_IMAGE_GOOD 和 QA_IMAGE_FAULT。"
            "不要把两图合为一个调用，不用Markdown远程图片替代。呈现后继续做历史来源查询，"
            "最后总结说明图片加载互不影响。"
        ),
        "inline_video": (
            "先 content.present external_video，source_url 必须等于已读取记录的原始video URL，"
            "title 为 QA_INLINE_VIDEO。不得 media.import_historical video，不下载、不转存视频，"
            "也不用外部打开链接替代内联播放器。呈现后继续查询来源，再给最终总结。"
        ),
        "chart_markdown_latex": (
            "用 files.publish content 分别发布以下两个 .vl.json 文件，"
            "再各自 content.present chart。"
            "第一图 title=QA_CHART_GOOD，description=两个来源的独立增长，spec="
            + json.dumps(GOOD_CHART, ensure_ascii=False, separators=(",", ":"))
            + "；第二图title=QA_CHART_FAULT，description=有意的渲染器故障，spec="
            + json.dumps(BAD_CHART, ensure_ascii=False, separators=(",", ":"))
            + "。第二spec用于真实故障隔离测试，不要改成有效mark。"
            "最终正文包含Markdown表格列 Source/Growth、两行A/12和B/8，以及 $$x^2+y^2=z^2$$。"
        ),
        "revision": (
            "先 content.present external_video，source_url=已核验video URL，"
            "title=QA_REVISION_VIDEO，"
            "不得下载或转存。随后用一次 events.search_history limit=20 查询两个订阅来源，"
            "再读两条独立原始记录，确认12%与8%的冲突。要求系统真实已验证发现及其文字修订；"
            "不要重复创建播放器，保留同一个媒体。最终总结包含这两个增长值。"
        ),
    }
    return (
        f"只读验收。先 events.get_historical_event period_id={fixture['period_id']} "
        f"event_id={fixture['event_id']}，读取授权媒体及原始URL。"
        + instructions[case_id]
        + f"不修改业务数据。最终最后一段只输出 {marker}。"
    )


def validate_media(evidence: Mapping[str, Any]) -> None:
    validate_live_evidence(evidence)
    case_id, media = evidence.get("case_id"), evidence.get("media", {})
    if (
        case_id not in MEDIA_CASES
        or media.get("scope") != "actual_browser_media_observation"
        or media.get("fixture_provider") is not False
        or type(evidence.get("tool_count")) is not int
        or evidence["tool_count"] < 1
        or media.get("preterminal", {}).get("before_terminal") is not True
        or media.get("preterminal", {}).get("before_final_receipt") is not True
    ):
        raise E2EError("media_not_observed_live")
    if case_id == "image" and not (
        media.get("image", {}).get("decoded") is True
        and media.get("image", {}).get("fault_aborted") is True
        and media.get("image", {}).get("sibling_survived") is True
    ):
        raise E2EError("image_decode_or_isolation_unproven")
    if case_id in {"inline_video", "revision"} and not (
        media.get("video", {}).get("played") is True
        and media.get("video", {}).get("time_advanced_seconds", 0) >= 0.2
        and media.get("video", {}).get("frames_advanced", 0) >= 2
        and media.get("video", {}).get("source_kind") == "verified_external_direct"
        and media.get("video", {}).get("download_requests") == 0
    ):
        raise E2EError("actual_inline_playback_unproven")
    if case_id == "chart_markdown_latex" and not all(
        media.get("chart", {}).get(key) is True
        for key in ("valid_svg", "isolated_failure", "markdown_table", "latex_rendered")
    ):
        raise E2EError("chart_markdown_latex_unproven")
    if case_id == "revision" and not all(
        media.get("revision", {}).get(key) is True
        for key in (
            "canonical_replacement",
            "same_video_node",
            "playback_continued",
            "reader_anchor",
        )
    ):
        raise E2EError("stable_media_revision_unproven")


def native_media(
    config: Config, evidence: Mapping[str, Any], fixture: Mapping[str, Any]
) -> dict[str, Any]:
    """At most 256 run headers / 1 MiB typed proof; never total Task history."""
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    validate_media_fixture(fixture)
    task, thread = task_binding(
        config, conversation_key=evidence["conversation_key"], simple_slice=True
    )
    scope = joint_preflight(config)["namespace_id"]
    if not isinstance(scope, str):
        raise E2EError("media_namespace_unproven")
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with db.connect_task_io(deadline=time.monotonic() + 2) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        header = read_run_header(connection, scope, TaskId(UUID(task)), evidence["run_id"], None)
        if header.anchor is None or header.control_only:
            raise E2EError("media_run_not_canonical")
        rows = connection.execute(
            "SELECT event_id,event_type,task_sequence,octet_length(payload::text) AS bytes "
            "FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
            "AND task_sequence BETWEEN %s AND %s ORDER BY task_sequence LIMIT 257",
            (scope, task, header.start, header.stop - 1 if header.stop else header.highwater),
        ).fetchall()
        if len(rows) > 256 or sum(row["bytes"] for row in rows) > 1_048_576:
            raise E2EError("media_canonical_proof_limit")
        selected = {
            "tool_call_proposed",
            "tool_execution_completed",
            "public_output",
            "model_response_received",
            "answer_committed",
        }
        points = []
        for row in rows:
            if row["event_type"] in selected:
                point = connection.execute(
                    "SELECT payload FROM session_events "
                    "WHERE deployment_namespace=%s AND event_id=%s",
                    (scope, row["event_id"]),
                ).fetchone()
                if point is None:
                    raise E2EError("media_canonical_source_missing")
                points.append({**row, "payload": point["payload"]})
    return validate_native_media_points(points, evidence, fixture, task=task, thread=thread)


def validate_native_media_points(
    points: list[dict[str, Any]],
    evidence: Mapping[str, Any],
    fixture: Mapping[str, Any],
    *,
    task: str,
    thread: str,
) -> dict[str, Any]:
    finals = [p for p in points if p["event_type"] == "answer_committed"]
    models = [p for p in points if p["event_type"] == "model_response_received"]
    tools = [
        p
        for p in points
        if p["event_type"] == "tool_execution_completed"
        and p["payload"].get("status") == "executed"
    ]
    parts = [
        (p, part)
        for p in tools
        for part in p["payload"].get("metadata", {}).get("content_parts", [])
    ]
    if len(finals) != 1 or not models or not tools:
        raise E2EError("media_real_model_tool_final_missing")
    proposals = {
        p["payload"].get("tool_call_id"): p
        for p in points
        if p["event_type"] == "tool_call_proposed"
    }
    for tool in tools:
        proposal = proposals.get(tool["payload"].get("tool_call_id"))
        if (
            proposal is None
            or proposal["task_sequence"] >= tool["task_sequence"]
            or proposal["payload"].get("tool_name") != tool["payload"].get("tool_name")
        ):
            raise E2EError("media_tool_receipt_not_correlated")
    history = [
        p
        for p in tools
        if p["payload"].get("tool_name") == "events.get_historical_event"
        and proposals[p["payload"]["tool_call_id"]]["payload"].get("arguments", {}).get("event_id")
        == fixture["event_id"]
    ]
    if not history:
        raise E2EError("media_entitled_source_not_read")
    if not all(
        p["payload"].get("provider") in {"deepseek", "openai", "openai-compatible"}
        and isinstance(p["payload"].get("model_call_id"), str)
        and re.fullmatch(r"[a-f0-9]{64}", str(p["payload"].get("request_hash", "")))
        and p["payload"].get("normalized_error") is None
        for p in models
    ):
        raise E2EError("media_fixture_or_unproved_model_provider")
    if any(p["task_sequence"] >= finals[0]["task_sequence"] for p, _ in parts):
        raise E2EError("media_presentation_not_preterminal")
    case_id = evidence["case_id"]
    if case_id == "image":
        imports = [
            p
            for p in tools
            if p["payload"].get("tool_name") == "media.import_historical"
            and p["payload"].get("metadata", {}).get("host_media_import") is True
        ]
        if len(imports) < 2 or len([part for _, part in parts if part.get("type") == "image"]) < 2:
            raise E2EError("image_real_import_and_presentation_missing")
    if case_id in {"inline_video", "revision"}:
        video = [
            part
            for _, part in parts
            if part.get("type") == "external_video"
            and part.get("sourceUrl") == fixture["video_url"]
        ]
        if (
            not video
            or any(part.get("type") == "video" for _, part in parts)
            or any(p["payload"].get("metadata", {}).get("media_kind") == "video" for p in tools)
        ):
            raise E2EError("external_video_was_not_direct")
        if not any(
            item.get("event_id") == fixture["event_id"]
            and item.get("original_url") == fixture["video_url"]
            for p in history
            for item in json.loads(p["payload"].get("output", "{}") or "{}").get("items", [])
        ):
            raise E2EError("external_video_source_not_in_real_read")
    if case_id == "chart_markdown_latex":
        proposed = [
            p["payload"]
            for p in points
            if p["event_type"] == "tool_call_proposed"
            and p["payload"].get("tool_name") == "files.publish"
        ]
        specs = [
            json.loads(p["arguments"]["content"])
            for p in proposed
            if isinstance(p.get("arguments", {}).get("content"), str)
        ]
        if (
            GOOD_CHART not in specs
            or BAD_CHART not in specs
            or len([part for _, part in parts if part.get("type") == "chart"]) < 2
        ):
            raise E2EError("chart_spec_source_unproven")
    if case_id == "revision":
        replacements = [
            p
            for p in points
            if p["event_type"] == "public_output" and p["payload"].get("replaces_output_id")
        ]
        browser_ids = {r["output_id"] for r in evidence["media"]["revision"]["replacements"]}
        if not replacements or not browser_ids <= {p["payload"]["output_id"] for p in replacements}:
            raise E2EError("browser_revision_not_canonical")
    return {
        "task_id": task,
        "host_thread": thread,
        "run_id": evidence["run_id"],
        "scope": "canonical_run_headers_and_bounded_media_receipts",
        "model_count": len(models),
        "tool_count": len(tools),
        "presentation_count": len(parts),
        "final_count": 1,
        "whole_history_hydrated": False,
        "fixture_provider": False,
    }


def run_media_case(
    config: Config,
    environment: Mapping[str, str],
    evidence_dir: Path,
    *,
    case_id: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Executable current-freeze slice; raises, never passes with obsolete images."""
    joint_preflight(config)
    if case_id == "revision":
        manifest = json.loads(Path(config.isolation_manifest).read_text())
        budget = docker(
            [
                "exec",
                manifest["containers"]["worker"]["id"],
                "python",
                "-c",
                "import os;print(os.getenv('ZEBRA_PUBLIC_OUTPUT_EXPRESSION_MAX_CALLS','0'))",
            ],
            timeout=5,
        ).strip()
        if not budget.isdigit() or int(budget) < 1:
            raise E2EError("revision_real_expression_disabled")
    identity = native_source_identity(config)
    if not identity or any(
        not isinstance(p, dict) or p.get("current_checkout_match") is not True
        for p in identity.values()
    ):
        raise E2EError("media_latest_freeze_not_deployed")
    marker = "ZEBRA_QA_SIMPLE_" + uuid4().hex
    prompt = media_prompt(case_id, marker, fixture)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    script = (
        Path(__file__).resolve().parents[3].parent
        / "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
    )
    inputs = {
        "case_id": case_id,
        "prompt": prompt,
        "media_fixture": dict(fixture),
        "base_url": config.bff_url,
        "cookie": config.session_cookie,
        "expected": marker,
        "timeout_ms": config.timeout_seconds * 1000,
        "python": sys.executable,
        "guard_script": str(Path(__file__).with_name("run_acceptance.py")),
        "cleanup_script": str(Path(__file__).with_name("terminal_probe.py")),
        "evidence_dir": str(evidence_dir.resolve()),
        "tls_spki": environment.get("ZEBRA_E2E_TLS_SPKI", ""),
    }
    result = subprocess.run(
        [environment.get("ZEBRA_E2E_NODE", "node"), str(script)],
        cwd=script.parent.parent,
        env=dict(environment),
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds + 60,
        check=False,
    )
    if result.returncode != 0:
        raise E2EError("media_real_browser_executor_failed")
    path = evidence_dir / (case_id.replace("_", "-") + ".json")
    if path.stat().st_size > 1_048_576:
        raise E2EError("media_browser_evidence_limit")
    evidence = json.loads(path.read_text())
    validate_media(evidence)
    return {
        "case_id": case_id,
        "status": "slice_passed",
        "source_identity": identity,
        "native": native_media(config, evidence, fixture),
        "browser": evidence,
        "full_goal_passed": False,
        "healthy_samples": 1,
    }


if __name__ == "__main__":
    import argparse
    import os

    from run_acceptance import REQUIRED_ENV
    from support import load_config

    parser = argparse.ArgumentParser(description="One real latest-freeze media slice, not all P1")
    parser.add_argument("--case", choices=sorted(MEDIA_CASES), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        config = load_config(os.environ, REQUIRED_ENV)
        fixture = seed_media(
            config,
            image_url=os.environ.get("ZEBRA_QA_MEDIA_IMAGE_URL", ""),
            video_url=os.environ.get("ZEBRA_QA_MEDIA_VIDEO_URL", ""),
        )
        report = run_media_case(
            config, os.environ, arguments.evidence_dir, case_id=arguments.case, fixture=fixture
        )
        (arguments.evidence_dir / "media-result.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    except (E2EError, ValueError, OSError, subprocess.SubprocessError):
        print("ZEBRA_JOINT_MEDIA=BLOCKED full_goal_passed=false")
        raise SystemExit(2) from None
    print("ZEBRA_JOINT_MEDIA=SLICE_PASSED full_goal_passed=false")
