"""Qualified Host mutation proof must permit a fresh read, never fabricate verification."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.domain.verification_evidence import VerificationResourceRef
from agent_core.harness.tool_freshness import (
    can_refresh_repeated_read,
    needs_post_mutation_verification,
    record_tool_freshness,
)

READ = frozenset({"case.get"})
WRITE = frozenset({"case.open"})


def call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=uuid4(),
        name=name,
        arguments={"item_id": "item-42"},
        created_at=datetime.now(UTC),
    )


def record(
    metadata: dict[str, object],
    tool: ToolCall,
    *,
    resource: str = "item-42",
    version: str = "2",
    postcondition: bool = True,
    epoch: int | None = None,
) -> dict[str, object]:
    ref = VerificationResourceRef(
        authority_issuer="https://business.example",
        namespace_id="tenant-a",
        host_app_id="host-a",
        resource_type="case",
        resource_id=resource,
    )
    result = ToolResult(
        tool_call_id=tool.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output="Observed business row",
        metadata={
            "route": "host_tool_gateway",
            "verification_resource_ref": ref.model_dump(mode="json"),
            "business_revision": version,
            "postcondition_met": postcondition,
        },
    )
    return record_tool_freshness(
        metadata, tool, result, read_only_tools=READ, mutation_tools=WRITE, observed_epoch=epoch
    )


def test_qualified_host_read_refreshes_once_after_each_mutation() -> None:
    read, write = call("case.get"), call("case.open")
    metadata = record({}, read, version="1")
    assert not can_refresh_repeated_read(read, metadata=metadata, read_only_tools=READ)
    metadata = record(metadata, write)
    assert can_refresh_repeated_read(read, metadata=metadata, read_only_tools=READ)
    assert not can_refresh_repeated_read(write, metadata=metadata, read_only_tools=READ)
    assert needs_post_mutation_verification(metadata, read_only_tools=READ)
    metadata = record(metadata, read)
    assert not can_refresh_repeated_read(read, metadata=metadata, read_only_tools=READ)
    assert not needs_post_mutation_verification(metadata, read_only_tools=READ)
    metadata = record(metadata, write, version="3")
    assert can_refresh_repeated_read(read, metadata=metadata, read_only_tools=READ)


@pytest.mark.parametrize(
    ("resource", "version", "postcondition", "epoch"),
    [
        ("foreign", "2", True, None),
        ("item-42", "1", True, None),
        ("item-42", "2", False, None),
        ("item-42", "2", True, 0),
    ],
)
def test_refresh_permission_is_not_resource_version_or_postcondition_proof(
    resource: str, version: str, postcondition: bool, epoch: int | None
) -> None:
    read = call("case.get")
    metadata = record(record({}, read, version="1"), call("case.open"))
    assert can_refresh_repeated_read(read, metadata=metadata, read_only_tools=READ)
    metadata = record(
        metadata, read, resource=resource, version=version, postcondition=postcondition, epoch=epoch
    )
    assert needs_post_mutation_verification(metadata, read_only_tools=READ)
