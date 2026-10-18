"""Legacy file reads preserve canonical Host ownership without creating bindings."""

from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec
from types import SimpleNamespace
from uuid import UUID

import pytest
from agent_core.domain import task_bindings
from agent_core.domain.events import EventType
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import SessionId
from agent_core.ports.session_artifact_read import SessionArtifact

TASK = "123e4567-e89b-12d3-a456-426614174001"
FILE = "0f49a531-64cd-4b20-a194-d85f1b28f04a"


def context():
    return HostContextEnvelope(
        grant_id="fresh",
        host_app_id="trench",
        namespace_id="tenant",
        workspace_ref="workspace",
        resource_refs=(
            HostResourceRef(type="thread", id="original-thread"),
            HostResourceRef(type="principal", id="owner"),
        ),
        scopes=("artifact.read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=10, max_model_tokens=1000, max_artifact_bytes=10000
        ),
        origin="https://trench.example",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


@pytest.mark.parametrize(
    "drift",
    [
        None,
        "host_app_id",
        "namespace_id",
        "workspace_ref",
        "origin",
        "principal",
        "thread",
        "scope",
        "expired",
    ],
)
def test_historical_host_comparison_never_uses_expired_grant_as_current_authority(drift):
    check = getattr(task_bindings, "require_legacy_artifact_host_context", None)
    assert check is not None, "Historical artifact ownership validation is missing"
    current = context()
    original = current.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(days=30)})
    if drift in {"host_app_id", "namespace_id", "workspace_ref", "origin"}:
        current = current.model_copy(update={drift: "other"})
    elif drift in {"principal", "thread"}:
        current = current.model_copy(
            update={
                "resource_refs": tuple(
                    ref.model_copy(update={"resource_id": "other"})
                    if ref.resource_type == drift
                    else ref
                    for ref in current.resource_refs
                )
            }
        )
    elif drift == "scope":
        current = current.model_copy(update={"scopes": ("agent.run",)})
    elif drift == "expired":
        current = original
    if drift is None:
        check(original, current, now=datetime.now(UTC))
    else:
        with pytest.raises(ValueError):
            check(original, current, now=datetime.now(UTC))


@pytest.mark.parametrize("published", [True, False])
def test_legacy_hook_requires_a_canonical_published_file(published):
    assert find_spec("zebra_agent_api.legacy_artifact_read") is not None
    module = import_module("zebra_agent_api.legacy_artifact_read")
    current = context()
    event = SimpleNamespace(
        event_type=EventType.TASK_PREPARED,
        payload={"host_context": current.model_dump(mode="json")},
    )

    class Events:
        def read_session_highwater(self, sid):
            return 2

        def read_session_status(self, sid):
            return "completed"

        def read_session_event_page(self, sid, after_sequence, **kwargs):
            assert after_sequence == -1 and kwargs == {"limit": 16, "max_bytes": 131072}
            return SimpleNamespace(events=(event,))

    artifact = SessionArtifact(
        "tool-run:5",
        SessionId(UUID(TASK)),
        5,
        "tool_run",
        "tool_output",
        "files.publish",
        f"artifact://{FILE}",
        "file",
        {"redacted": False, "truncated": False},
        {"tool_name": "files.publish" if published else "web.fetch", "status": "executed"},
    )
    app = SimpleNamespace(
        stores=SimpleNamespace(
            events=Events(), artifacts=SimpleNamespace(get_for_session=lambda *_: artifact)
        )
    )
    assert module.legacy_artifact_read_allowed(app, current, TASK, FILE) is published
    assert module.legacy_artifact_read_allowed(app, current, TASK, "tool-run:5") is published
    assert module.artifact_read_target("POST", f"/tasks/{TASK}/artifacts/{FILE}/prune") is None
    assert module.artifact_read_target("GET", f"/tasks/{TASK}/artifacts/{FILE}/preview") == (
        TASK,
        FILE,
    )


def test_legacy_gateway_exposes_only_exact_file_reads():
    import re
    from pathlib import Path

    text = Path("docker/trench-acceptance/Caddyfile").read_text()
    pattern = re.search(r"path_regexp (.+)", text).group(1)
    for suffix in ("", "/preview", "/download"):
        assert re.fullmatch(pattern, f"/tasks/{TASK}/artifacts/{FILE}{suffix}")
    for suffix in ("", "/artifacts", f"/artifacts/{FILE}/prune", "/messages"):
        assert not re.fullmatch(pattern, f"/tasks/{TASK}{suffix}")
    assert "method GET HEAD" in text


def test_internal_content_read_keeps_artifact_scope_and_canonical_publication():
    module = import_module("zebra_agent_api.legacy_artifact_read")
    assert module.artifact_read_target("GET", f"/tasks/{TASK}/artifacts/tool-run:5/content") == (
        TASK,
        "tool-run:5",
    )
