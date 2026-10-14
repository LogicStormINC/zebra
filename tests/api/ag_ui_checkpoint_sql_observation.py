"""Observed native SQL: fixed scalar metadata shapes and bounded Event body pages."""

import hashlib
import re
from contextvars import ContextVar
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
import pytest
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_replay import TaskRunHeader
from agent_storage.postgres.task_io import TaskIoConnection, current_task_io_deadline
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict


class PgSqlObservation:
    """Record attempted SQL; PG read-only transactions independently reject any DML."""

    PROTOCOL_PAGE_SHA = "3c9390a26104e84a5a34ac6f44e7847bc309f4a5d337bf508b3359899efdb81a"

    COMMAND_ID_POINT = (
        "SELECT event_id,session_id,sequence,event_type,actor,created_at, "
        "payload->>'command_id' AS command_id FROM session_events "
        "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=%s "
        "AND event_id=%s AND session_id=%s AND sequence=%s"
    )

    # ponytail: fixed reviewed SQL shapes require re-review when queries change.
    # Metadata results exclude Event bodies; scalar guards may still read PG JSON/TOAST.
    METADATA_SHAPES = {
        "eeffd3018ecc2e8a5003b1dae2798054ddedcb22e89d053afb34f5843a8dfb47": 3,
        "3985fafb4762c7f156a2d22be409978a36fa7e34f9874aca34a6cc7b1cba040d": 10,
        "553a3bd7254ed7a83d3706ba73c9dd6eff3b92c83fa4392199100b3b8669b633": 12,
        "cd3d40514cfb4ff20202f95637f5d6e782d9d1f4935eaa1aa1f790c37827f088": 4,
    }
    HANDOFF_PREDICATE = (
        "(e.event_type='session_handoff_received' AND (m.predecessor_id IS NULL "
        "OR jsonb_typeof(e.payload->'root_session_id') IS DISTINCT FROM 'string' "
        "OR e.payload->>'root_session_id' IS DISTINCT FROM t.task_id::text "
        "OR jsonb_typeof(e.payload->'parent_session_id') IS DISTINCT FROM 'string' "
        "OR e.payload->>'parent_session_id' IS DISTINCT FROM m.predecessor_id::text "
        "OR jsonb_typeof(e.payload->'stage_index') IS DISTINCT FROM 'number' "
        "OR e.payload->>'stage_index' IS DISTINCT FROM m.segment_index::text)) AS invalid_origin"
    )
    ACCEPTED_POINT = (
        "SELECT event_id,session_id,sequence,event_type,actor,created_at, "
        "payload->>'command_id' AS command_id FROM session_events "
        "WHERE deployment_namespace=(SELECT ns FROM args) AND task_id=(SELECT tid FROM args) "
        "AND task_sequence=(SELECT position FROM args) AND event_id=(SELECT eid FROM args) "
        "AND session_id=(SELECT sid FROM args) AND sequence=(SELECT sequence FROM args) "
        "AND (SELECT enabled FROM args)"
    )

    RUN_COLUMNS = (
        "task_id,task_sequence,event_id,session_id,sequence,event_type,"
        "replay_command_kind AS command_kind,replay_run_id AS command_run_id,"
        "replay_internal_continuation AS internal_continuation,replay_header_ready"
    )

    @classmethod
    def metadata_shape(cls, statement: str, params: Any) -> bool:
        arity = cls.METADATA_SHAPES.get(hashlib.sha256(statement.encode()).hexdigest())
        if arity is None:
            return False
        if arity == 4:
            assert not re.search(r"\bpayload\b", statement)
            assert statement.count("SELECT " + cls.RUN_COLUMNS + " FROM session_events") == 3
            assert len(params) == 4 and isinstance(params[0], str)
            assert isinstance(params[1], UUID)
            assert isinstance(params[2], str) and 0 < len(params[2]) <= 256
            assert params[3] is None or type(params[3]) is int and params[3] >= -1
            return True
        if arity == 12:
            assert statement.startswith(
                "SELECT accepted,binding,terminal,pending,receipt,control,outbox FROM "
            )
            assert statement.count(cls.ACCEPTED_POINT) == 1
            assert len(re.findall(r"\bpayload\b", statement)) == 1
            assert len(params) == 12 and isinstance(params[0], str)
            assert all(isinstance(params[index], UUID) for index in (1, 3, 4))
            assert all(type(params[index]) is int and params[index] >= 0 for index in (2, 5))
            assert isinstance(params[6], str) and 0 < len(params[6]) <= 256
            assert type(params[7]) is bool and all(isinstance(v, str) for v in params[8:11])
            assert isinstance(params[11], list) and all(isinstance(v, str) for v in params[11])
            return True
        assert statement.count(cls.HANDOFF_PREDICATE) == 1
        assert len(re.findall(r"\bpayload\b", statement)) == (6 if arity == 3 else 7)
        assert len(params) == arity and isinstance(params[0], str)
        assert isinstance(params[1], UUID) or (arity == 3 and params[1] is None)
        if arity == 3:
            assert isinstance(params[2], UUID) or params[2] is None
            assert params[1] is not None or params[2] is not None
        else:
            assert statement.count(cls.ACCEPTED_POINT) == 1
            assert all(isinstance(params[index], str) for index in (2, 3, 4))
            assert type(params[5]) is bool
            assert all(isinstance(v, str) for v in params[6:9]) if params[5] else all(
                v is None for v in params[6:9]
            )
            assert isinstance(params[9], list) and all(isinstance(v, str) for v in params[9])
        return True

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.writes: list[str] = []
        self.body_reads: list[str] = []
        self.body_limits: list[int] = []
        self.body_connections: list[str] = []
        self.rejected_body_reads: list[str] = []
        self.connections: set[str] = set()
        self.command_points: list[tuple[object, ...]] = []
        self.command_connections: list[str] = []
        self.bodies = False
        self.protocol_admission_reads: list[tuple[object, ...]] = []
        self.protocol_admission_connections: list[str] = []
        self.protocol_validator_calls = 0
        self.protocol_validation_failures = 0
        self._protocol_point: ContextVar[tuple[Any, ...] | None] = ContextVar(
            "observed_protocol_point", default=None
        )
        loader_active: ContextVar[bool] = ContextVar("observed_protocol_loader", default=False)
        execute = psycopg.Cursor.execute

        from agent_integrations import run_stream_admission as admission
        from zebra_agent_api import stream_v2_authority

        original_load = admission.load_run_stream_admission
        original_validate = admission.validate_accepted_session_command
        observer = self

        # ponytail: this test delegate observes the loader's two existing reads;
        # add an explicit observation if the loader's read contract ever grows.
        class AdmissionReads:
            def __init__(self, tasks: Any, task_id: Any, run_id: str) -> None:
                self.tasks, self.task_id, self.run_id = tasks, task_id, run_id
                self.run: TaskRunHeader | None = None

            def read_run_header(self, task_id: Any, run_id: str) -> TaskRunHeader:
                assert (task_id, run_id) == (self.task_id, self.run_id)
                run = self.tasks.read_run_header(task_id, run_id)
                assert isinstance(run, TaskRunHeader) and run.task_id == task_id
                assert run.run_id == run_id
                self.run = run
                return run

            def read_event_page(
                self, task_id: Any, after: int, *, through_sequence: int,
                limit: int, max_bytes: int,
            ) -> TaskEventPage:
                assert self.run is not None and self.run.anchor is not None
                anchor = self.run.anchor
                assert anchor.event_type is EventType.SESSION_COMMAND_ACCEPTED
                assert task_id == self.task_id == anchor.task_id
                assert type(after) is int and after == anchor.task_sequence - 1
                assert type(through_sequence) is int and through_sequence == anchor.task_sequence
                assert type(limit) is int and limit == 1
                assert type(max_bytes) is int and 0 < max_bytes <= 1_048_576
                namespace = self.tasks._database.deployment_namespace
                options = conninfo_to_dict(self.tasks._database._dsn).get("options", "")
                assert "-c default_transaction_read_only=on" in options
                token = observer._protocol_point.set((namespace, task_id, anchor, max_bytes))
                try:
                    page = self.tasks.read_event_page(
                        task_id, after, through_sequence=through_sequence,
                        limit=limit, max_bytes=max_bytes,
                    )
                finally:
                    observer._protocol_point.reset(token)
                assert isinstance(page, TaskEventPage)
                assert len(page.events) == 1 and not page.has_more and page.byte_count <= max_bytes
                entry = page.events[0]
                assert (entry.task_id, entry.task_sequence, entry.event.event_id,
                        entry.segment_id, entry.segment_sequence) == (
                    task_id, anchor.task_sequence, anchor.event_id,
                    anchor.segment_id, anchor.segment_sequence,
                )
                assert entry.event.session_id == anchor.segment_id
                assert entry.event.sequence == anchor.segment_sequence
                assert entry.event.event_type is EventType.SESSION_COMMAND_ACCEPTED
                return page

        def protocol_load(tasks: Any, task_id: Any, run_id: str) -> Any:
            token = loader_active.set(True)
            try:
                return original_load(AdmissionReads(tasks, task_id, run_id), task_id, run_id)
            finally:
                loader_active.reset(token)

        def protocol_validate(*args: Any, **kwargs: Any) -> Any:
            if loader_active.get():
                observer.protocol_validator_calls += 1
            try:
                return original_validate(*args, **kwargs)
            except ValueError:
                if loader_active.get():
                    observer.protocol_validation_failures += 1
                raise

        monkeypatch.setattr(admission, "load_run_stream_admission", protocol_load)
        monkeypatch.setattr(stream_v2_authority, "load_run_stream_admission", protocol_load)
        monkeypatch.setattr(admission, "validate_accepted_session_command", protocol_validate)

        def observed_execute(
            cursor: psycopg.Cursor[Any],
            query: Any,
            params: Any = None,
            **kwargs: Any,
        ) -> psycopg.Cursor[Any]:
            self.connections.add(type(cursor.connection).__name__)
            statement = " ".join(
                (
                    query.as_string(cursor.connection)
                    if isinstance(query, sql.Composable)
                    else str(query)
                ).split()
            )
            if re.search(
                r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|COPY|TRUNCATE)\b",
                statement,
                re.IGNORECASE,
            ) or re.search(r"\bFOR (UPDATE|SHARE)\b", statement, re.IGNORECASE):
                self.writes.append(statement)
            if statement == self.COMMAND_ID_POINT:
                assert len(params) == 6 and isinstance(params[0], str)
                assert all(isinstance(params[index], UUID) for index in (1, 3, 4))
                assert all(type(params[index]) is int and params[index] >= 0 for index in (2, 5))
                self.command_points.append(tuple(params))
                self.command_connections.append(type(cursor.connection).__name__)
                return execute(cursor, query, params, **kwargs)
            if self.metadata_shape(statement, params):
                if len(params) == 12:
                    self.command_points.append(tuple(params[:6]))
                    self.command_connections.append(type(cursor.connection).__name__)
                return execute(cursor, query, params, **kwargs)
            event_aliases = re.findall(
                r"\b(?:FROM|JOIN) session_events (?:AS )?(\w+)", statement, re.IGNORECASE
            )
            event_body = any(
                re.search(
                    rf"\b{alias}\.\*|\b(?:to_jsonb|row_to_json)\s*\(\s*{alias}\s*\)",
                    statement, re.IGNORECASE,
                )
                for alias in event_aliases
            )
            if "session_events" in statement and (event_body or re.search(
                r"\bpayload\b|(?:\bSELECT\s+|,\s*)\*",
                statement,
                re.IGNORECASE,
            )):
                point = self._protocol_point.get()
                if point is not None:
                    namespace, task_id, anchor, _ = point
                    assert hashlib.sha256(statement.encode()).hexdigest() == self.PROTOCOL_PAGE_SHA
                    assert len(params) == 5
                    assert isinstance(params[0], str) and isinstance(params[1], UUID)
                    assert all(type(params[index]) is int for index in (2, 3, 4))
                    assert tuple(params) == (
                        namespace, task_id, anchor.task_sequence - 1, anchor.task_sequence, 1
                    )
                    assert isinstance(cursor.connection, TaskIoConnection)
                    deadline = current_task_io_deadline()
                    assert deadline is not None
                    assert monotonic() < cursor.connection.deadline <= deadline + 0.001
                    self.protocol_admission_reads.append((
                        namespace, task_id, anchor.task_sequence, anchor.event_id,
                        anchor.segment_id, anchor.segment_sequence,
                    ))
                    self.protocol_admission_connections.append(type(cursor.connection).__name__)
                    return execute(cursor, query, params, **kwargs)
                self.body_reads.append(statement)
                self.body_connections.append(type(cursor.connection).__name__)
                try:
                    assert self.bodies, "PG preflight hydrated an Event body"
                    assert "event.task_sequence>%s" in statement
                    assert "event.task_sequence<=%s" in statement
                    assert "ORDER BY event.task_sequence LIMIT %s" in statement
                    assert 1 <= params[-1] <= 256
                except AssertionError:
                    self.rejected_body_reads.append(statement)
                    raise
                self.body_limits.append(params[-1])
            return execute(cursor, query, params, **kwargs)

        # ClientCursor inherits this execute method; native connection creation is untouched.
        monkeypatch.setattr(psycopg.Cursor, "execute", observed_execute)

