import pytest
from agent_storage import sqlite_control_plane_stores


def test_sqlite_control_plane_stores_require_filesystem_database() -> None:
    with pytest.raises(ValueError, match="filesystem-backed database"):
        sqlite_control_plane_stores(":memory:")
