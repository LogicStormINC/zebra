"""Default-composition E2E: API create → Worker loop → agent.research → wakeup.

Drives the REAL default cloud composition — the public API create path
(atomic admission, frozen binding, full-body idempotency) and the default
Worker loop service — against real PostgreSQL and MinIO. Only the model
transport is a scripted local OpenAI-compatible stub. Verifies the durable
delegation chain end to end:

1. create returns 201 and the identical full body replays idempotently,
2. the parent delegates via agent.research and suspends waiting_children
   (no premature SESSION_COMPLETED),
3. the child runs READ_ONLY with a narrowed frozen binding,
4. the child terminal wakeup resumes the parent with the real result
   injected, and the parent then completes.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID, uuid4

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_storage.runtime_composition import CloudCompositionSettings
from zebra_agent_api.factory import create_app
from zebra_agent_worker.loop import build_worker_loop_service

PARENT_PROMPT = "PARENT_E2E: summarise the deployment runbook evidence."
CHILD_OBJECTIVE = "CHILD_E2E_OBJECTIVE: locate the deployment runbook section."
PARENT_RESUMED_ANSWER = "PARENT_RESUMED_WITH_CHILD_EVIDENCE"
CHILD_ANSWER = "CHILD_SUMMARY_E2E"

MODEL_KEY_ENV = "ZEBRA_E2E_MODEL_KEY"
# Scripted-delegation width: 1 (default) or 2 (multi-child scenario).
SCRIPT_MODE: dict[str, int] = {"children": 1}
CHILD_OBJECTIVE_2 = "CHILD_E2E_OBJECTIVE_2: locate the rollback playbook section."


def _completion(content: str, finish: str = "stop") -> dict[str, object]:
    return {
        "id": f"chatcmpl-{uuid4()}",
        "object": "chat.completion",
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
    }


def _tool_completion(call_id: str, name: str, arguments: dict[str, str]) -> dict[str, object]:
    return {
        "id": f"chatcmpl-{uuid4()}",
        "object": "chat.completion",
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 16, "completion_tokens": 16, "total_tokens": 32},
    }


def _multi_tool_completion(
    name: str, delegations: list[tuple[str, str]]
) -> dict[str, object]:
    """One completion proposing several agent.research calls at once."""

    tool_calls = [
        {
            "id": f"call-{uuid4()}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(
                    {"objective": objective, "delegation_reason": reason}
                ),
            },
        }
        for objective, reason in delegations
    ]
    return {
        "id": f"chatcmpl-{uuid4()}",
        "object": "chat.completion",
        "model": "stub-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls,
                },
            }
        ],
        "usage": {"prompt_tokens": 24, "completion_tokens": 24, "total_tokens": 48},
    }


def _as_stream_events(completion_payload: dict[str, object]) -> bytes:
    """Convert one scripted completion into a single-event SSE stream."""

    choice = completion_payload["choices"][0]
    assert isinstance(choice, dict)
    message = choice["message"]
    assert isinstance(message, dict)
    delta: dict[str, object] = {"role": "assistant"}
    if message.get("content"):
        delta["content"] = message["content"]
    if message.get("tool_calls"):
        delta["tool_calls"] = [
            {**call, "index": index}
            for index, call in enumerate(message["tool_calls"])
        ]
    chunk = {
        "id": completion_payload.get("id"),
        "model": completion_payload.get("model"),
        "choices": [
            {"index": 0, "finish_reason": choice.get("finish_reason"), "delta": delta}
        ],
        "usage": completion_payload.get("usage"),
    }
    events = [f"data: {json.dumps(chunk)}", "data: [DONE]", ""]
    return ("\n\n".join(events)).encode("utf-8")


def _scripted_response(body: dict[str, object]) -> dict[str, object]:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return _completion("ok")
    contents = [
        message.get("content")
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), str)
    ]
    joined = "\n".join(contents)
    tools = body.get("tools")
    advertised = (
        {
            tool.get("function", {}).get("name")
            for tool in tools
            if isinstance(tool, dict)
        }
        if isinstance(tools, list)
        else set()
    )
    # Providers normalize dotted tool names (agent.research → agent_research);
    # the scripted response must echo the ADVERTISED name verbatim.
    research_tool = next(
        (name for name in advertised if isinstance(name, str) and "research" in name),
        None,
    )
    child_evidence = joined.count(CHILD_ANSWER)
    if PARENT_PROMPT in joined and research_tool is not None:
        expected_children = SCRIPT_MODE["children"]
        if child_evidence >= expected_children and "PARENT_RESUMED" not in joined:
            # The parent may only finish once EVERY child's REAL answer has
            # been injected into the conversation.
            return _completion(PARENT_RESUMED_ANSWER)
        if expected_children >= 2:
            return _multi_tool_completion(
                research_tool,
                [
                    (
                        CHILD_OBJECTIVE,
                        "bounded read-only evidence needs isolation",
                    ),
                    (
                        CHILD_OBJECTIVE_2,
                        "the rollback evidence is independent",
                    ),
                ],
            )
        return _tool_completion(
            f"call-{uuid4()}",
            research_tool,
            {
                "objective": CHILD_OBJECTIVE,
                "delegation_reason": "bounded read-only evidence needs isolation",
            },
        )
    if CHILD_OBJECTIVE_2 in joined or CHILD_OBJECTIVE in joined:
        return _completion(CHILD_ANSWER)
    return _completion("ok")


class _StubModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw) if raw else {}
            payload = _scripted_response(body)
            if body.get("stream") is True:
                encoded = _as_stream_events(payload)
                content_type = "text/event-stream"
            else:
                encoded = json.dumps(payload).encode("utf-8")
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except Exception as exc:  # pragma: no cover - stub failure surface
            encoded = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:
        return


def _settings(stub_url: str, dsn: str):
    from zebra_agent_config.settings import (
        ApiSettings,
        ModelSettings,
        ZebraAgentSettings,
    )

    return ZebraAgentSettings(
        profile="cloud",
        database_url=dsn,
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="openai",
            api_key_env=MODEL_KEY_ENV,
            base_url=stub_url,
            model="stub-model",
        ),
    )


def test_default_chain_delegates_suspends_and_resumes(
    postgres_dsn: str,
    cloud_composition: CloudCompositionSettings,
    namespace: str,
    stub_model_server: str,
    tmp_path: Path,
) -> None:
    cloud = CloudCompositionSettings(
        dsn=postgres_dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud_composition.memory_cursor_signing_key,
        artifact_objects=cloud_composition.artifact_objects,
        history_scope=cloud_composition.history_scope,
        continuation_scope=cloud_composition.continuation_scope,
    )
    settings = _settings(stub_model_server, postgres_dsn)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    app = create_app(
        database_path=tmp_path / "unused.sqlite",
        settings=settings,
        cloud_composition=cloud,
    )

    payload = {
        "title": "default-chain-e2e",
        "prompt": PARENT_PROMPT,
        "workspace": str(workspace_root),
        "execute": True,
    }
    first = app.create_session(payload, idempotency_key="e2e-key-1")
    assert first.status_code == 201, first.body
    session_id = str(first.body["session_id"])

    replayed = app.create_session(payload, idempotency_key="e2e-key-1")
    assert replayed.status_code == 201
    assert replayed.body == first.body, "idempotent replay must return the full body"

    conflict_payload = {**payload, "prompt": "different prompt entirely"}
    conflict = app.create_session(conflict_payload, idempotency_key="e2e-key-1")
    assert conflict.status_code == 409
    assert conflict.body["status"] == "idempotency_conflict"

    loop = build_worker_loop_service(
        database_path=tmp_path / "unused.sqlite",
        settings=settings,
        cloud_composition=cloud,
    )
    loop.run(
        worker_id="e2e-worker",
        max_cycles=80,
        stop_when_idle=False,
        idle_sleep_seconds=0.05,
    )

    stores = app.stores
    from agent_core.domain.identifiers import TaskId

    events = stores.events.list_for_session(SessionId(UUID(session_id)))
    event_types = [event.event_type for event in events]
    delegated = [
        event for event in events if event.event_type is EventType.SUBAGENT_DELEGATED
    ]
    assert delegated, f"parent never delegated; saw {[t.value for t in event_types]}"
    child_task_id = str(delegated[0].payload["child_task_id"])

    assert EventType.SESSION_SUSPENDED in event_types, "parent must suspend"
    suspended = [
        event for event in events if event.event_type is EventType.SESSION_SUSPENDED
    ]
    assert suspended[0].payload["reason"] == "waiting_children"
    assert suspended[0].payload["child_task_ids"] == [child_task_id]
    assert EventType.SESSION_RESUMED in event_types, "wakeup must resume the parent"
    assert EventType.SESSION_COMPLETED in event_types, "parent must complete after join"

    completed_index = event_types.index(EventType.SESSION_COMPLETED)
    suspended_index = event_types.index(EventType.SESSION_SUSPENDED)
    assert suspended_index < completed_index, "suspension must precede completion"

    session = stores.sessions.get_session(SessionId(UUID(session_id)))
    assert session is not None
    assert session.status.value == "completed"

    child_session = stores.sessions.get_session(SessionId(UUID(child_task_id)))
    assert child_session is not None
    assert child_session.status.value == "completed"

    from agent_storage.postgres.subagent_delegation import (
        PostgresSubagentDelegationStore,
    )

    store = PostgresSubagentDelegationStore(
        postgres_dsn, deployment_namespace=namespace
    )
    link = store.get_link(TaskId(UUID(child_task_id)))
    assert link is not None
    assert link.terminal_at is not None, "wakeup must terminalize the delegation link"

    from agent_storage.postgres.task_admission import load_task_binding

    child_binding = load_task_binding(
        postgres_dsn,
        deployment_namespace=namespace,
        task_id=TaskId(UUID(child_task_id)),
    )
    assert child_binding is not None, "child must carry a frozen binding"
    assert set(child_binding.effective_capabilities) == {"agent.execute", "evidence.read"}
    assert child_binding.task_id == child_task_id

    completed_event = events[completed_index]
    assistant = completed_event.payload.get("metadata", {}).get("assistant_message", "")
    assert PARENT_RESUMED_ANSWER in str(assistant), (
        "parent final answer must reflect the injected child result"
    )

    # The wakeup command must be HARNESS-actor and carry the child's REAL
    # terminal answer (metadata.assistant_message), not a lifecycle label.
    wakeup_commands = [
        event
        for event in events
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and event.actor.value == "harness"
        and event.payload.get("kind") == "resume"
    ]
    assert wakeup_commands, "the trusted harness wakeup command must exist"
    delivered = wakeup_commands[0].payload["payload"]["child_results"]
    assert delivered[0]["child_task_id"] == child_task_id
    assert delivered[0]["status"] == "completed"
    assert CHILD_ANSWER in delivered[0]["summary"], (
        "wakeup must carry the child's real model answer"
    )
