"""Explicit publication permits media delivery without exposing internal binaries."""

from pathlib import Path

import pytest
from agent_security import PolicyProfile
from agent_storage import SQLiteToolRunStore
from fastapi.testclient import TestClient
from session_artifact_support import (
    _seed_payload_backed_tool_artifact,
    _seed_session,
    _seed_workspace_policy,
)
from zebra_agent_api import create_http_app


@pytest.mark.parametrize(
    "mime,payload",
    [
        ("application/json", b'{"mark":"bar"}'),
        ("image/png", b"png-bytes"),
        ("video/mp4", b"0123456789"),
    ],
)
def test_only_successfully_published_media_can_preview_under_workspace_policy(
    tmp_path: Path, mime, payload
):
    database = tmp_path / "sessions.sqlite"
    session = _seed_session(database)
    _seed_workspace_policy(database, session.session_id, PolicyProfile.WORKSPACE_WRITE.value)
    _seed_payload_backed_tool_artifact(
        database, session.session_id, mime_type=mime, payload=payload
    )
    store = SQLiteToolRunStore(database)
    record = store.list_for_session(session.session_id)[0]
    client = TestClient(create_http_app(database))
    path = f"/tasks/{session.session_id}/artifacts/tool-run:5"
    assert client.get(f"{path}/preview").status_code == 409

    published = record.model_copy(update={"tool_name": "files.publish"})
    store.upsert(published)
    for suffix in ("preview", "download"):
        result = client.get(f"{path}/{suffix}")
        assert result.status_code == 200, result.text
        assert result.content == payload
    assert client.head(f"{path}/preview").headers["content-length"] == str(len(payload))
    assert client.get(f"{path}/preview", headers={"Range": "bytes=1-3"}).content == payload[1:4]

    for changes in ({"status": "failed"}, {"output": "token=secret-value"}):
        store.upsert(published.model_copy(update=changes))
        assert client.get(f"{path}/preview").status_code == 409
    store.upsert(published)
    _seed_workspace_policy(database, session.session_id, PolicyProfile.READ_ONLY.value)
    assert client.get(f"{path}/preview").status_code == 409
