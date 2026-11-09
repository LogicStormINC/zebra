"""Owned disposable cloud-root acceptance; run from the Native repository root."""

import sys
import tempfile
from pathlib import Path


def main() -> None:
    if not Path("pyproject.toml").is_file():
        raise ValueError("run from Native repository root")
    sys.path.insert(0, str(Path.cwd()))
    import json
    from dataclasses import replace

    import pytest
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_storage import postgres_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app
    from zebra_agent_api.runtime_gate_termination import PATH

    from tests.agent_storage.test_host_management import host_management_dsn
    from tests.api.test_runtime_gate_management import command, gate
    from tests.api.test_runtime_gate_termination import subject, termination

    class NoObjects:
        def read(self, *args, **kwargs):
            raise AssertionError("no artifact IO in gate check")

    database = host_management_dsn.__wrapped__()
    dsn = next(database)
    try:
        with tempfile.TemporaryDirectory(prefix="ca-p5-composition-") as directory:
            patch = pytest.MonkeyPatch()
            fixture = gate.__wrapped__(Path(directory), dsn, patch)
            g = next(fixture)
            term = subject.__wrapped__(g, Path(directory))
            try:
                scope = OpaqueAuthorityScope(
                    authority_issuer=g.approval.scope.authority_issuer,
                    namespace_id=g.approval.scope.namespace_id,
                )
                stores = postgres_control_plane_stores(
                    dsn,
                    deployment_namespace=g.approval.scope.namespace_id,
                    memory_cursor_signing_key=b"a" * 32,
                    artifact_objects=NoObjects(),
                    history_scope=scope,
                    continuation_scope=scope,
                )
                app = create_http_app(
                    settings=replace(
                        g.cfg,
                        runtime_gate_config=None,
                        runtime_gate_termination_config=str(term[4]),
                    ),
                    stores=stores,
                    host_grant_origins=("https://business.example",),
                )
                with TestClient(app) as client:
                    headers = term[3]
                    request = termination(json.dumps(command("open")))
                    response = client.post(PATH, headers=headers, json=request)
                    assert response.status_code == 200, response.text
                    original = response.json()["original"]
                    assert original["outcome"] == "no_gate_commit"
                    assert original["proofScope"] == "original_gate_command_only"
                    response = client.get(
                        PATH, headers={**headers, "X-Runtime-Operation": request["termination_id"]}
                    )
                    assert response.status_code == 200, response.text
                    assert response.json()["original"] == original
                    assert (
                        client.get("/management/v1/runtime-gates", headers=g.headers).status_code
                        == 503
                    )
                print(
                    "PASS full cloud API termination-only configuration: original POST/GET; "
                    "no gate/task dispatch"
                )
            finally:
                try:
                    fixture.close()
                finally:
                    patch.undo()
    finally:
        database.close()


if __name__ == "__main__":
    main()
