"""Owned disposable cloud-root acceptance; run from the Native repository root."""

import sys
import tempfile
from pathlib import Path


def main() -> None:
    if not Path("pyproject.toml").is_file():
        raise ValueError("run from Native repository root")
    sys.path.insert(0, str(Path.cwd()))
    import pytest
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_storage import postgres_control_plane_stores
    from fastapi.testclient import TestClient
    from zebra_agent_api import create_http_app

    from tests.agent_storage.test_host_management import host_management_dsn
    from tests.api.test_runtime_gate_management import PATH, gate

    class NoObjects:
        def read(self, *args, **kwargs):
            raise AssertionError("no artifact IO in gate check")

    database = host_management_dsn.__wrapped__()
    dsn = next(database)
    try:
        with tempfile.TemporaryDirectory(prefix="ca-p5-composition-") as directory:
            patch = pytest.MonkeyPatch()
            fixture = gate.__wrapped__(Path(directory), dsn, patch)
            subject = next(fixture)
            try:
                scope = OpaqueAuthorityScope(
                    authority_issuer=subject.approval.scope.authority_issuer,
                    namespace_id=subject.approval.scope.namespace_id,
                )
                stores = postgres_control_plane_stores(
                    dsn,
                    deployment_namespace=subject.approval.scope.namespace_id,
                    memory_cursor_signing_key=b"a" * 32,
                    artifact_objects=NoObjects(),
                    history_scope=scope,
                    continuation_scope=scope,
                )
                app = create_http_app(
                    settings=subject.cfg,
                    stores=stores,
                    host_grant_origins=("https://business.example",),
                )
                with TestClient(app) as client:
                    response = client.get(PATH, headers=subject.headers)
                    assert response.status_code == 200, response.text
                    assert response.json()["scope"] == subject.approval.scope.model_dump(
                        mode="json"
                    )
                    assert response.json()["activationAuthorized"] is False
                print("PASS full cloud API composition: scoped machine GET; no business dispatch")
            finally:
                try:
                    fixture.close()
                finally:
                    patch.undo()
    finally:
        database.close()


if __name__ == "__main__":
    main()
