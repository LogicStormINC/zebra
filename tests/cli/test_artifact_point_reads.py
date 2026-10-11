"""CLI detail/content/control use the same native exact lookup as HTTP."""

import base64

import pytest
from agent_storage import SQLiteArtifactStore
from zebra_agent_cli.artifact_read import (
    prune_artifact,
    read_artifact_content,
    read_artifact_detail,
)

from tests.api.session_artifacts.session_artifact_support import (
    _seed_payload_backed_tool_artifact,
    _seed_session,
)


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("read", [read_artifact_detail, read_artifact_content, prune_artifact])
def test_cli_point_read_does_not_enumerate(tmp_path, monkeypatch, public, read):
    path = tmp_path / "points.sqlite"
    session = _seed_session(path)
    payload = _seed_payload_backed_tool_artifact(path, session.session_id)

    def no_listing(*args, **kwargs):
        raise AssertionError("CLI point lookup enumerated siblings")

    monkeypatch.setattr(SQLiteArtifactStore, "list_for_session", no_listing)
    result = read(
        database_path=path,
        session_id=str(session.session_id),
        artifact_id=str(payload.artifact_id) if public else "tool-run:5",
    )
    assert result["status"] in {"ok", "pruned"}, result
    if read is read_artifact_content:
        assert base64.b64decode(result["content_base64"]) == b"pytest passed"
