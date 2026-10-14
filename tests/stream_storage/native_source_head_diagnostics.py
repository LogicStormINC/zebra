"""Native admission timing only; preserve real timeout/thread/source semantics."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from time import monotonic, thread_time

import httpx
from agent_storage.postgres.task_io import current_task_io_deadline

from tests.stream_storage.telemetry import LABEL, phase


def install_diagnostics(monkeypatch, captured, read_timings, timing_lock):
    admission_timings = []

    def append(record):
        with timing_lock:
            admission_timings.append(record)

    original_client = httpx.AsyncClient.__init__

    def measured_client(client, *args, **kwargs):
        started, cpu = monotonic(), thread_time()
        try:
            return original_client(client, *args, **kwargs)
        finally:
            append(
                {
                    "kind": "client-construction",
                    "label": LABEL.get(),
                    "started": started,
                    "seconds": monotonic() - started,
                    "thread_cpu_seconds": thread_time() - cpu,
                }
            )

    monkeypatch.setattr(httpx.AsyncClient, "__init__", measured_client)

    def trace(target, name, label):
        original = getattr(target, name)

        @wraps(original)
        def measured(*args, **kwargs):
            began = monotonic()
            deadline = current_task_io_deadline()
            record = {
                "kind": "method",
                "label": LABEL.get(),
                "method": label,
                "entered": began,
                "deadline_remaining": deadline - began if deadline is not None else None,
            }
            if label == "taskio-connect":
                candidates = [began + kwargs.get("timeout_seconds", 2)]
                candidates.extend(d for d in (deadline, kwargs.get("deadline")) if d is not None)
                remaining = min(candidates) - began
                record["connect_deadline_remaining"] = remaining
                record["connect_operation_remaining"] = remaining - min(0.2, remaining * 0.1)
            elif label == "taskio-resolve":
                record["supplied_deadline_remaining"] = args[1] - began
            with phase(LABEL.get() + "/" + label):
                try:
                    return original(*args, **kwargs)
                except BaseException as exc:
                    record["exception"] = type(exc).__name__
                    raise
                finally:
                    record["exited"] = monotonic()
                    append(record)
                    with timing_lock:
                        read_timings.setdefault(label, []).append((began, monotonic() - began))

        monkeypatch.setattr(target, name, measured)

    from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
    from agent_storage.postgres import stream_proof_batch, stream_source_head, task_replay_headers
    from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
    from agent_storage.postgres.direct_control import PostgresDirectControl
    from agent_storage.postgres.task_io import TaskIoConnections
    from zebra_agent_api import http_host_auth, stream_v2_reader
    from zebra_agent_api.stream_v2_authority import V2ReadAuthority

    for target, name, label in (
        (type(captured["authorizer"]), "authorize", "http-jti"),
        (stream_proof_batch.StreamProofSnapshot, "task_id_for_session", "task-mapping"),
        (PostgresDirectControl, "read_task_binding_snapshot", "principal-binding"),
        (TaskIoConnections, "connect", "taskio-connect"),
        (TaskIoConnections, "_resolve", "taskio-resolve"),
        (http_host_auth, "validate_host_target", "http-target"),
        (stream_proof_batch.StreamProofSnapshot, "binding", "session-binding"),
        (V2ReadAuthority, "qualify", "tail-qualify"),
        (AgUiCheckpointObserver, "snapshot", "snapshot"),
        (AgUiCheckpointObserver, "read_page", "page"),
        (stream_source_head, "read_checkpoint_source_head", "qualified-head"),
        (stream_proof_batch.StreamProofSnapshot, "read_task_header", "task-header"),
        (
            stream_proof_batch.StreamProofSnapshot,
            "read_event_projection_header",
            "event-projection-header",
        ),
        (task_replay_headers, "read_event_header", "event-header"),
        (task_replay_headers, "read_run_header", "run-header"),
        (stream_source_head, "read_source_head", "qualified-source"),
        (stream_v2_reader, "discover", "redis-discovery"),
    ):
        trace(target, name, label)

    restore_snapshot = PostgresAgentTaskStore.read_checkpoint_snapshot

    @contextmanager
    def measured_restore(*args, **kwargs):
        began = monotonic()
        with phase(LABEL.get() + "/event-restore"):
            try:
                with restore_snapshot(*args, **kwargs) as reader:
                    yield reader
            finally:
                with timing_lock:
                    read_timings.setdefault("event-restore", []).append(
                        (began, monotonic() - began)
                    )

    monkeypatch.setattr(PostgresAgentTaskStore, "read_checkpoint_snapshot", measured_restore)

    from zebra_agent_api import ag_ui_task_view

    original_read, original_thread = (
        ag_ui_task_view.authorized_async_read,
        ag_ui_task_view.to_thread,
    )

    async def measured_read(read, **kwargs):
        submitted = monotonic()
        deadline = kwargs.get("request_deadline")
        record = {
            "kind": "async",
            "label": LABEL.get(),
            "submitted": submitted,
            "deadline_remaining": deadline - submitted if deadline is not None else None,
        }

        async def callback():
            record["entered"] = monotonic()
            try:
                return await read()
            except BaseException as exc:
                record["exception"] = type(exc).__name__
                raise
            finally:
                record["exited"] = monotonic()

        try:
            result = await original_read(callback, **kwargs)
            record["result_type"] = type(result).__name__
            record["result_status"] = getattr(result, "status_code", None)
            return result
        finally:
            record["completed"] = monotonic()
            append(record)

    async def measured_thread(function, *args, **kwargs):
        record = {"kind": "thread", "label": LABEL.get(), "submitted": monotonic()}

        def operation():
            record["entered"] = monotonic()
            deadline = current_task_io_deadline()
            record["deadline_remaining"] = (
                deadline - record["entered"] if deadline is not None else None
            )
            try:
                return function(*args, **kwargs)
            except BaseException as exc:
                record["exception"] = type(exc).__name__
                raise
            finally:
                record["exited"] = monotonic()
                append(record)

        return await original_thread(operation)

    original_async_thread = asyncio.to_thread

    async def measured_host_thread(function, *args, **kwargs):
        if not (
            getattr(function, "__module__", None) == http_host_auth.__name__
            and getattr(function, "__qualname__", None) == "authorize_request.<locals>.operation"
        ):
            return await original_async_thread(function, *args, **kwargs)
        closure = dict(zip(function.__code__.co_freevars, function.__closure__, strict=True))
        deadline = closure["deadline"].cell_contents
        submitted = monotonic()
        record = {
            "kind": "host-thread",
            "label": LABEL.get(),
            "submitted": submitted,
            "submitted_deadline_remaining": deadline - submitted,
        }

        def operation():
            record["entered"] = monotonic()
            record["deadline_remaining"] = deadline - record["entered"]
            try:
                return function(*args, **kwargs)
            except BaseException as exc:
                record["exception"] = type(exc).__name__
                raise
            finally:
                record["exited"] = monotonic()
                append(record)

        return await original_async_thread(operation)

    monkeypatch.setattr(asyncio, "to_thread", measured_host_thread)
    monkeypatch.setattr(ag_ui_task_view, "authorized_async_read", measured_read)
    monkeypatch.setattr(ag_ui_task_view, "to_thread", measured_thread)
    return admission_timings


@asynccontextmanager
async def api_loop_probe(records):
    async def sample():
        started, cpu = monotonic(), thread_time()
        count, total, maximum = 0, 0.0, 0.0
        try:
            while True:
                expected = monotonic() + 0.025
                await asyncio.sleep(0.025)
                lag = max(0.0, monotonic() - expected)
                count, total, maximum = count + 1, total + lag, max(maximum, lag)
        finally:
            records.append(
                {
                    "kind": "api-loop",
                    "seconds": monotonic() - started,
                    "thread_cpu_seconds": thread_time() - cpu,
                    "samples": count,
                    "max_lag_seconds": maximum,
                    "mean_lag_seconds": total / count if count else None,
                }
            )

    probe = asyncio.create_task(sample())
    try:
        yield
    finally:
        probe.cancel()
        await asyncio.gather(probe, return_exceptions=True)


async def capture_asgi_exception(app, scope, receive, send, records, lock):
    entered, phase_name, last_send = monotonic(), "before_response", None

    async def measured_send(message):
        nonlocal phase_name, last_send
        last_send = monotonic()
        if message["type"] == "http.response.start":
            phase_name = "response_started"
        elif message["type"] == "http.response.body":
            phase_name = "streaming" if message.get("more_body", False) else "completed"
        await send(message)

    try:
        await app(scope, receive, measured_send)
    except BaseException as exc:
        pending, classes = [exc], []
        while pending:
            error = pending.pop()
            if isinstance(error, BaseExceptionGroup):
                pending.extend(error.exceptions)
            elif not isinstance(error, asyncio.CancelledError):
                classes.append(type(error).__name__)
        if classes:
            with lock:
                records.append(
                    {
                        "kind": "asgi-exception",
                        "label": LABEL.get(),
                        "phase": phase_name,
                        "exception": type(exc).__name__,
                        "leaf_classes": sorted(set(classes)),
                        "entered": entered,
                        "raised": monotonic(),
                        "last_send": last_send,
                    }
                )
        raise


def failure_diagnostics(state, telemetry, requested_seconds):
    started = getattr(state, "steady_started", None)
    actual_exit = getattr(state, "observation_exited", None)
    return {
        "admitted": sum(getattr(state, "admitted", [])),
        "recovered": sum(getattr(state, "recovered", [])),
        "admission_errors": state.admission_errors,
        "telemetry": telemetry.report(),
        "read_timings": state.read_timings,
        "admission_timings": state.admission_timings,
        "requested_seconds": requested_seconds,
        "steady_started": started,
        "scheduled_steady_end": started + requested_seconds if started is not None else None,
        "steady_ended": getattr(state, "steady_ended", None),
        "observation_exited": actual_exit,
        "observed_steady_seconds": (
            actual_exit - started if started is not None and actual_exit is not None else None
        ),
        "lease_heartbeats": getattr(state, "completed_lease_heartbeats", 0),
        "completed_steady_window": False,
        "slo_pass": False,
    }
