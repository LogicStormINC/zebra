"""Local native Worker/API -> authenticated HTTP -> actual official HttpAgent gate.

The provider is controlled and every Task is generated in the owned temp folder.
Cloud same-PG initial admission and signed-cursor authority have separate native gates.
"""

import asyncio
import json
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import patch

import uvicorn
from agent_core.application import SessionBootstrapService
from agent_core.domain.events import EventType
from agent_core.domain.turns import InteractionMode
from zebra_agent_api.http import create_http_app
from zebra_agent_config import ApiSettings
from zebra_agent_worker.ag_ui_composition import configure_agui_projection_work
from zebra_agent_worker.command_consumer import SessionCommandConsumer

from tests.api.test_agui_native_prepare import prepared_surface
from tests.worker.execution.worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
)

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agui-http-gate-") as temporary:
        folder = Path(temporary)
        build = SessionBootstrapService.build
        with patch.object(
            SessionBootstrapService,
            "build",
            lambda self, command: build(
                self, replace(command, interaction_mode=InteractionMode.CONVERSATION)
            ),
        ):
            adapter, headers, body, database, task = prepared_surface(folder)
        app = adapter.app
        baseline = _assistant_only_gateway(settings=app.settings)
        with patch("zebra_agent_worker.execution.build_model_gateway", lambda settings: baseline):
            _build_execution_service(database).execute_session(task, worker_id="agui-http-baseline")
        expected_revision = app.stores.sessions.get_session(task).current_sequence
        token = "isolated-http-gate-authorization"
        settings = replace(
            app.settings,
            api=ApiSettings(auth_token=token),
            stream=replace(app.settings.stream, agui_profiles_enabled=True),
        )
        app = replace(app, settings=settings)
        worker = _assistant_only_gateway(settings=settings)
        stop, completed = Event(), Event()
        executions = []
        unauthorized_counts = []
        observation_counts = []
        observed_inputs = []
        with patch("zebra_agent_api.http.create_app", lambda *a, **k: app):
            http = create_http_app(database, settings=settings, stores=app.stores)

        @http.middleware("http")
        async def observe_count(request, call_next):
            if not request.url.path.endswith("/stream"):
                return await call_next(request)
            # Count read-only effects after the one native writer has fully drained,
            # including its finalization writes; live-tail pacing has separate gates.
            assert await asyncio.to_thread(completed.wait, 10), "native Worker did not complete"
            before = len(app.stores.events.list_for_session(task))
            if request.headers.get("Authorization") != "Bearer " + token:
                response = await call_next(request)
                unauthorized_counts.append(
                    (before, len(app.stores.events.list_for_session(task)), response.status_code)
                )
                return response
            observation_counts.append(before)
            if request.method == "POST":
                observed_inputs.append(await request.json())
            return await call_next(request)

        projections = configure_agui_projection_work(app.stores, settings, None, None)
        assert projections is not None and len(projections.consumers) == 6
        consumer = SessionCommandConsumer(app.stores, _build_execution_service(database))

        def work() -> None:
            with patch("zebra_agent_worker.execution.build_model_gateway", lambda settings: worker):
                while not stop.is_set():
                    result = consumer.consume_once(
                        worker_id="agui-http-gate", lease_ttl_seconds=30
                    )
                    if result.status == "executed":
                        executions.append(result)
                        completed.set()
                    stop.wait(0.02)

        config = uvicorn.Config(http, host="127.0.0.1", port=0, log_level="error", access_log=False)
        sock = config.bind_socket()
        port = sock.getsockname()[1]
        server = uvicorn.Server(config)
        serving = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        working = Thread(target=work, daemon=True)
        try:
            projections.start()
            serving.start()
            working.start()
            deadline = monotonic() + 10
            while not server.started:
                assert monotonic() < deadline, "native HTTP server failed to start"
                sleep(0.01)
            metadata = folder / "input.json"
            metadata.write_text(
                json.dumps(
                    {
                        "origin": f"http://127.0.0.1:{port}",
                        "taskId": str(task),
                        "internalRunId": "run-1",
                        "segmentId": str(task),
                        "expectedRevision": expected_revision,
                        "headers": {
                            "Authorization": "Bearer " + token,
                            "X-Zebra-Client-Session": headers["X-Zebra-Client-Session"],
                            "X-Zebra-Client-Fence": headers["X-Zebra-Client-Fence"],
                        },
                        "input": body["input"],
                    }
                )
            )
            metadata.chmod(0o600)
            command = [
                str(ROOT / "sdks/typescript/node_modules/.bin/tsx"),
                str(ROOT / "tests/conformance/agui_contract/http_gate.mts"),
                str(metadata),
            ]
            result = subprocess.run(
                command,
                cwd=ROOT / "sdks/typescript",
                env=os.environ,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode:
                from zebra_agent_api.ag_ui_standard_http import accepted_input

                run = app.stores.tasks.read_run_header(task, "run-1")
                expected = accepted_input(app.stores.tasks, task, run.anchor).model_dump(
                    mode="json", by_alias=True
                )
                actual = observed_inputs[-1]
                fields = [
                    key
                    for key in expected.keys() | actual.keys()
                    if expected.get(key) != actual.get(key)
                ]
                raise AssertionError(
                    result.stdout + result.stderr + " differing input fields: " + repr(fields)
                )
            assert len(executions) == 1
            assert len(unauthorized_counts) == 1
            assert unauthorized_counts[0][0] == unauthorized_counts[0][1]
            assert unauthorized_counts[0][2] == 401
            assert observation_counts and all(
                n == observation_counts[0] for n in observation_counts
            )
            events = app.stores.events.list_for_session(task)
            assert len(events) == observation_counts[0], (
                "observation changed native execution events"
            )
            assert (
                len([e for e in events if e.event_type is EventType.SESSION_COMMAND_ACCEPTED]) == 1
            )
            assert len(worker.requests) == 1 and "ACTUAL NEW MESSAGE TO THE MODEL" in repr(
                worker.requests
            )
            print(
                "Actual Worker -> authenticated Python HTTP -> official HttpAgent: PASS; "
                "1 admission, 1 model, 0 observation writes"
            )
        finally:
            stop.set()
            server.should_exit = True
            projections.close()
            working.join(5)
            serving.join(5)
            sock.close()


if __name__ == "__main__":
    main()
