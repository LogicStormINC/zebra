"""Real partial-result cases, bounded source proof. Remaining eleven executors stay open."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from joint_acceptance import validate_live_evidence
from support import Config, E2EError, task_binding


def public_prompt(case_id: str, marker: str, seed: Mapping[str, Any]) -> str:
    if case_id not in {"multi_source", "tool_only"}:
        raise ValueError("public_case_executor_unimplemented")
    return (
        f"请对我订阅的 QA {seed['seed_id']} 两个来源做只读摘要。"
        "使用 events.search_history 宽查询 limit=20，不读取全文。"
        "先给带覆盖范围的已确认发现，再给简短总结。"
        "第一页不是完整覆盖，不得把互相冲突的12%和8%增长结论去重删除。"
        "不要修改订阅或数据。"
        + ("所有工具调用前不要输出正文，让系统按真实执行反馈。" if case_id == "tool_only" else "")
        + f"最终总结最后一段只放验收标记 {marker}。"
    )


def validate_partial(evidence: Mapping[str, Any]) -> None:
    validate_live_evidence(evidence)
    if (
        evidence.get("case_id") not in {"multi_source", "tool_only"}
        or type(evidence.get("public_output_count")) is not int
        or evidence["public_output_count"] < 1
        or type(evidence.get("tool_count")) is not int
        or evidence["tool_count"] < 1
        or not any(
            row.get("before_terminal") is True and row.get("before_final_receipt") is True
            for row in evidence.get("public_visibility", [])
        )
        or not any(
            row.get("type") == "public_output"
            and row.get("meaningful") is True
            and row.get("evidence_basis") == "verified_result"
            and row.get("coverage_qualified") is True
            for row in evidence["frames"]
        )
    ):
        raise ValueError("verified_partial_not_proven_live")


def native_partial(config: Config, evidence: Mapping[str, Any]) -> dict[str, Any]:
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_replay_headers import read_run_header

    task, thread = task_binding(
        config, conversation_key=evidence["conversation_key"], simple_slice=True
    )
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    scope = manifest["namespace_id"]
    db = PostgresDatabase(config.zebra_database_dsn, deployment_namespace=scope)
    with db.connect_task_io(deadline=time.monotonic() + 2) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        header = read_run_header(c, scope, TaskId(UUID(task)), evidence["run_id"], None)
        if header.anchor is None or header.control_only:
            raise E2EError("partial_run_not_canonical")
        rows = c.execute(
            "SELECT event_id,event_type,task_sequence FROM session_events "
            "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence BETWEEN %s AND %s "
            "ORDER BY task_sequence LIMIT 257",
            (scope, task, header.start, header.stop - 1 if header.stop else header.highwater),
        ).fetchall()
        if len(rows) > 256:
            raise E2EError("partial_header_evidence_limit")
        points = [
            row
            for row in rows
            if row["event_type"]
            in {
                "tool_execution_completed",
                "public_output",
                "model_response_received",
            }
        ]
        facts, outputs, models = [], [], []
        for row in points:
            point = c.execute(
                "SELECT payload->'metadata'->'public_facts' AS facts,"
                "payload->>'tool_name' AS tool_name,payload->>'tool_call_id' AS tool_call_id,"
                "payload->>'output_id' AS output_id,payload->>'origin' AS origin,"
                "payload->>'evidence_basis' AS basis,payload->'evidence_refs' AS refs,"
                "payload->>'assistant_message' IN ('','Tool calls proposed.') AS model_tool_only,"
                "payload->>'latency_ms' AS latency_ms,"
                "payload->>'time_to_first_public_text_ms' AS first_public_text_ms "
                "FROM session_events WHERE deployment_namespace=%s AND event_id=%s",
                (scope, row["event_id"]),
            ).fetchone()
            if point is None:
                raise E2EError("partial_point_source_missing")
            if row["event_type"] == "tool_execution_completed" and point["facts"]:
                fact = point["facts"]
                if point["tool_name"] == "events.search_history" and (
                    fact.get("query_completed") is True
                    and fact.get("partial_sample") is True
                    and fact.get("total_count", 0) > fact.get("returned_count", 0)
                    and fact.get("returned_source_count", 0) >= 2
                ):
                    facts.append(
                        {
                            "tool_call_id": point["tool_call_id"],
                            "facts": fact,
                            "task_sequence": row["task_sequence"],
                        }
                    )
            elif row["event_type"] == "public_output" and point["basis"] == "verified_result":
                outputs.append(
                    {
                        "output_id": point["output_id"],
                        "origin": point["origin"],
                        "refs": point["refs"],
                        "task_sequence": row["task_sequence"],
                    }
                )
            elif row["event_type"] == "model_response_received":
                models.append(
                    {
                        "tool_only": point["model_tool_only"],
                        "latency_ms": point["latency_ms"],
                        "first_public_text_ms": point["first_public_text_ms"],
                    }
                )
    finals = [row for row in rows if row["event_type"] == "answer_committed"]
    if (
        len(finals) != 1
        or not facts
        or not outputs
        or not any(
            fact["tool_call_id"] in output["refs"]
            and fact["task_sequence"] < output["task_sequence"] < finals[0]["task_sequence"]
            for fact in facts
            for output in outputs
        )
    ):
        raise E2EError("partial_not_backed_by_real_receipt")
    if evidence["case_id"] == "tool_only" and (
        not any(row["tool_only"] is True for row in models)
        or not any(row["origin"] == "system" for row in outputs)
    ):
        raise E2EError("real_tool_only_model_not_observed")
    return {
        "task_id": task,
        "host_thread": thread,
        "run_id": evidence["run_id"],
        "scope": "canonical_header_and_point_public_receipt_metadata",
        "facts": facts,
        "outputs": outputs,
        "model_timings": models,
        "final_count": 1,
        "whole_history_hydrated": False,
        "recovery_duplicate_milestone_gate": "not_yet_executed",
        "full_goal_passed": False,
    }
