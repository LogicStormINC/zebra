import asyncio
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from pydantic import ValidationError

from tests.api.test_extension_reads import MCP, SCOPE, SKILL


@pytest.mark.parametrize("kind", ["skill", "mcp"])
def test_toggle_preserves_record_and_cas(kind: Literal["skill", "mcp"]) -> None:
    store = AsyncMock(spec=ExtensionStore)
    record = SKILL if kind == "skill" else MCP
    getter = store.get_skill if kind == "skill" else store.get_mcp
    saver = store.save_skill if kind == "skill" else store.save_mcp
    getter.return_value = record
    identifier = SKILL.installation_id if kind == "skill" else MCP.connection_id
    result = asyncio.run(set_extension_enabled(
        store=store, scope=SCOPE, kind=kind, object_id=identifier,
        expected_revision=1, enabled=False,
    ))
    assert result.model_dump() == record.model_dump() | {"enabled": False, "revision": 2}
    assert saver.await_args.kwargs["expected_revision"] == 1
    saver.side_effect = ExtensionRevisionConflictError()
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(set_extension_enabled(
            store=store, scope=SCOPE, kind=kind, object_id=identifier,
            expected_revision=1, enabled=False,
        ))
    assert saver.await_count == 2


def test_noop_checks_revision_and_never_writes() -> None:
    store = AsyncMock(spec=ExtensionStore)
    store.get_skill.return_value = SKILL
    assert asyncio.run(set_extension_enabled(
        store=store, scope=SCOPE, kind="skill", object_id=SKILL.installation_id,
        expected_revision=1, enabled=True,
    )) is SKILL
    with pytest.raises(ExtensionRevisionConflictError):
        asyncio.run(set_extension_enabled(
            store=store, scope=SCOPE, kind="skill", object_id=SKILL.installation_id,
            expected_revision=2, enabled=True,
        ))
    store.save_skill.assert_not_called()


@pytest.mark.parametrize("record", [
    MCP, SKILL.model_copy(update={"installation_id": "other"}),
    SKILL.model_copy(update={"scope": SCOPE.model_copy(update={"workspace_id": "other"})}),
])
def test_bad_adapter_identity_never_writes(record: object) -> None:
    store = AsyncMock(spec=ExtensionStore)
    store.get_skill.return_value = record
    with pytest.raises(ExtensionNotFoundError):
        asyncio.run(set_extension_enabled(
            store=store, scope=SCOPE, kind="skill", object_id=SKILL.installation_id,
            expected_revision=1, enabled=False,
        ))
    store.save_skill.assert_not_called()
    store.save_mcp.assert_not_called()


@pytest.mark.parametrize("override", [
    {"enabled": 1}, {"enabled": "false"}, {"expected_revision": True},
    {"expected_revision": "1"}, {"expected_revision": 0}, {"object_id": " "},
    {"kind": "other"}, {"scope": {}},
])
def test_strict_arguments_before_storage(override: dict[str, object]) -> None:
    store = AsyncMock(spec=ExtensionStore)
    args = dict(store=store, scope=SCOPE, kind="skill", object_id="a",
                expected_revision=1, enabled=False) | override
    with pytest.raises(ValidationError):
        asyncio.run(set_extension_enabled(**args))  # type: ignore[arg-type]
    assert store.mock_calls == []
