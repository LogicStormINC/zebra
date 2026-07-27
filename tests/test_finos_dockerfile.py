from __future__ import annotations

from pathlib import Path

DOCKERFILE_PATH = Path(__file__).resolve().parents[1] / "Dockerfile.finos"


def test_finos_image_runs_as_the_existing_persistent_volume_owner() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "USER 999:999" in dockerfile
    assert "10002" not in dockerfile
    assert "chown 999:999 /data" in dockerfile
    assert "chown 999:999 /var/lib/finos/zebra" in dockerfile
    assert "ZEBRA_DATABASE_URL=/data/sessions.sqlite" in dockerfile
    assert "ZEBRA_TASK_WORKSPACE_ROOT=/var/lib/finos/zebra/task-workspaces" in dockerfile
