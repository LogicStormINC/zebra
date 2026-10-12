"""Bounded native model source/index pages; no proof authority is cached here."""

from collections.abc import Iterator
from typing import Any

from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.events import SessionEvent

from agent_storage.postgres.coverage_proof_prefetch import prefetch_proof


def original_rows(
    connection: Any, sql: str, parameters: tuple[Any, ...], upper: int | None,
    *, artifacts: Any = None,
) -> Iterator[Any]:
    # Preflight requires one joined row per Session sequence before paging.
    # Use execute so recovery read witnesses and deadline checks remain composed.
    cursor = -1
    while upper is not None and cursor < upper:
        rows = connection.execute(
            "SELECT * FROM (" + sql + ") originals WHERE sequence>%s AND sequence<=%s "
            "ORDER BY sequence LIMIT 100",
            (*parameters, cursor, upper),
        ).fetchall()
        if not rows:
            return
        if artifacts is not None:
            refs = tuple(CoverageModelUsageReceipt.model_validate(row["receipt"]).checkpoint_ref
                         for row in rows)
            if any(ref is None for ref in refs):
                raise ValueError("settled MODEL replay requires an original checkpoint")
            prefetch_proof(artifacts, tuple(ref for ref in refs if ref is not None))
        yield from rows
        cursor = rows[-1]["sequence"]


def model_rows(
    connection: Any, deployment: str, binding: Any, types: tuple[Any, ...],
    *, record_ids: list[str] | None = None, artifacts: Any = None,
) -> Iterator[Any]:
    upper = connection.execute(
        """SELECT max(sequence) AS last FROM session_events WHERE deployment_namespace=%s
           AND session_id=%s AND payload->>'namespace'=%s AND payload->>'run_id'=%s
           AND event_type=ANY(%s)""",
        (deployment, binding.session_id, binding.namespace, binding.run_id, list(types)),
    ).fetchone()["last"]
    if upper is None:
        return
    cursor = -1
    count = 0
    selection = "" if record_ids is None else """AND (
        e.event_type='coverage_model_budget_initialized'
        OR e.payload #>> '{reservation,key,record_id}'=ANY(%s)
        OR e.payload #>> '{receipt,reservation,key,record_id}'=ANY(%s))"""
    while True:
        rows = connection.execute(
            f"""SELECT e.*,w.event_digest AS witness_digest FROM session_events e
               LEFT JOIN coverage_model_events w ON w.deployment_namespace=e.deployment_namespace
               AND w.namespace=%s AND w.run_id=%s AND w.sequence=e.sequence
               WHERE e.deployment_namespace=%s AND e.session_id=%s
               AND e.payload->>'namespace'=%s AND e.payload->>'run_id'=%s
               AND e.event_type=ANY(%s) {selection} AND e.sequence<=%s AND e.sequence>%s
               ORDER BY e.sequence LIMIT 100""",
            (
                binding.namespace,
                binding.run_id,
                deployment,
                binding.session_id,
                binding.namespace,
                binding.run_id,
                list(types),
                *((record_ids, record_ids) if record_ids is not None else ()),
                upper,
                cursor,
            ),
        ).fetchall()
        if not rows:
            return
        refs = []
        for row in rows:
            if row["event_type"] == "coverage_model_usage_recorded":
                ref = CoverageModelUsageReceipt.model_validate(row["payload"]["receipt"])
                if ref.checkpoint_ref is None:
                    raise ValueError("settled MODEL replay requires an original checkpoint")
                refs.append(ref.checkpoint_ref)
        prefetch_proof(artifacts, tuple(refs))
        for row in rows:
            count += 1
            if count > 400001:
                raise ValueError("model projection/source exceeds bounded replay count")
            yield row
        cursor = rows[-1]["sequence"]
        if cursor >= upper or len(rows) < 100:
            return


def indexed_calls(
    connection: Any, deployment: str, binding: Any, *, record_ids: list[str] | None = None,
) -> Iterator[Any]:
    cursor = ""
    count = 0
    selection = "" if record_ids is None else "AND reservation #>> '{key,record_id}'=ANY(%s)"
    while True:
        rows = connection.execute(
            f"""SELECT * FROM coverage_model_calls WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s AND reservation_key>%s
               {selection} ORDER BY reservation_key LIMIT 100""",
            (deployment, binding.namespace, binding.run_id, cursor,
             *((record_ids,) if record_ids is not None else ())),
        ).fetchall()
        if not rows:
            return
        for row in rows:
            count += 1
            if count > 200000:
                raise ValueError("model projection/source exceeds bounded replay count")
            yield row
        cursor = rows[-1]["reservation_key"]
        # The enclosing run lock or RR snapshot pins this exact keyset.
        if len(rows) < 100:
            return


def task_events(connection: Any, deployment: str, binding: Any) -> Iterator[SessionEvent]:
    cursor = -1
    count = 0
    while True:
        rows = connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND event_type='task_prepared' AND sequence>%s ORDER BY sequence LIMIT 100""",
            (deployment, binding.session_id, cursor),
        ).fetchall()
        if not rows:
            return
        for row in rows:
            count += 1
            if count > 400001:
                raise ValueError("model Task source exceeds bounded replay count")
            yield SessionEvent.model_validate(row)
        cursor = rows[-1]["sequence"]
