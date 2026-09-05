from unittest.mock import MagicMock

import pytest
from agent_storage.postgres.migration_runner import require_current_schema
from agent_storage.postgres.migration_types import PostgresMigrationError
from agent_storage.postgres.migrations import MIGRATIONS


@pytest.mark.parametrize("valid", [True, False])
def test_startup_requires_exact_schema(monkeypatch, valid):
    connection = MagicMock()
    rows = [(m.version, m.name, m.checksum) for m in MIGRATIONS]
    connection.execute.return_value.fetchall.return_value = rows if valid else rows[:-1]
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr("agent_storage.postgres.migration_runner.psycopg.connect", connect)
    if valid:
        require_current_schema("unused")
    else:
        with pytest.raises(PostgresMigrationError, match="schema differs"):
            require_current_schema("unused")


@pytest.mark.parametrize("parent_namespace", ["trench:user-1", "other-user", None])
def test_legacy_handoff_requires_matching_parent(parent_namespace):
    from agent_storage.postgres.command_wakeup import _validated_host_context
    from zebra_agent_api.session_binding import _build_binding_snapshot

    from tests.api.test_session_binding_renewal import _context

    context = _context(grant_id="test")
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=context,
        definition_snapshot_digest="a" * 64,
    )
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [
        {
            "namespace_id": None,
            "task_id": binding.task_id,
            "snapshot_json": binding.model_dump(mode="json"),
            "binding_digest": binding.binding_digest,
        },
        {"namespace_id": parent_namespace} if parent_namespace else None,
    ]
    if parent_namespace == context.namespace_id:
        assert _validated_host_context(connection, "zebra", MagicMock()) == context
    else:
        with pytest.raises(ValueError, match="bounded Host scope"):
            _validated_host_context(connection, "zebra", MagicMock())
