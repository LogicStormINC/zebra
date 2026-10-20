"""Snapshot create replay identity without Worker activation or write bypass."""

import json
import os
import subprocess
import sys
from datetime import timedelta

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot_invocation import CoverageInvocation, HostCoverageInvoke
from agent_integrations.host_tools.contracts import HostToolManifest

from tests.agent_integrations.test_coverage_snapshot import (
    AUTHORITY,
    CONTRACT,
    NOW,
    frozen_manifest,
)
from tests.agent_integrations.test_coverage_snapshot_preparation import setup_source


def invocation(
    callback: HostCoverageInvoke,
    *,
    authority: HostContextEnvelope = AUTHORITY,
    manifest: HostToolManifest | None = None,
    history_ref: str = "history",
    later: int = 0,
) -> CoverageInvocation:
    return CoverageInvocation(
        authority=authority,
        history_ref=history_ref,
        manifest=manifest or frozen_manifest(),
        invoke=callback,
        admitted_effect_invoke=callback,
        now=lambda: NOW + timedelta(seconds=later),
    )


def ready(
    call: ToolCall,
    context: HostContextEnvelope,
    *,
    idempotency_key: str | None = None,
    required_resource: HostResourceRef | None = None,
    manifest: HostToolManifest | None = None,
) -> ToolResult:
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        output=json.dumps({"status": "ready", "call_id": str(call.tool_call_id)}),
    )


def create_id(
    *,
    authority: HostContextEnvelope = AUTHORITY,
    manifest: HostToolManifest | None = None,
    history_ref: str = "history",
    later: int = 0,
    key: str = "admitted-key",
) -> str:
    host = invocation(
        ready, authority=authority, manifest=manifest, history_ref=history_ref, later=later
    )
    return str(host.call("create", {}, authority, host.budget(authority), key)["call_id"])


def test_fresh_source_accepts_original_stored_descriptor_receipt():
    source, wire, options = setup_source()
    admitted = options["admitted_effect_invoke"]
    stored: ToolResult | None = None
    calls: list[ToolCall] = []

    def replay(call, context, **kwargs):
        nonlocal stored
        calls.append(call)
        if stored is None:
            stored = admitted(call, context, **kwargs)
        # Fresh deserialization, retaining the original ID, like the fenced ledger.
        return ToolResult.model_validate_json(stored.model_dump_json())

    options["admitted_effect_invoke"] = replay
    first = type(source)(**options).create(
        CONTRACT,
        authority=AUTHORITY,
        idempotency_key="admitted-key",
    )
    fresh = type(source)(**{**options, "now": lambda: NOW + timedelta(seconds=1)})
    assert fresh.create(CONTRACT, authority=AUTHORITY, idempotency_key="admitted-key") == first
    assert calls[0].tool_call_id == calls[1].tool_call_id
    assert calls[0].created_at != calls[1].created_at
    assert sum(c["toolName"] == "dataset.snapshot.create" for c in wire.calls) == 1


def test_exact_raw_key_retry_reuses_operation_and_whitespace_variant_is_distinct():
    source, wire, options = setup_source()
    admitted = options["admitted_effect_invoke"]
    operations: dict[str, ToolResult] = {}
    calls: list[tuple[str, ToolCall]] = []

    def host_idempotency(call, context, *, idempotency_key, **kwargs):
        assert isinstance(idempotency_key, str)
        calls.append((idempotency_key, call))
        # Host keys operations by the actual callback key, without normalization.
        if idempotency_key not in operations:
            operations[idempotency_key] = admitted(
                call, context, idempotency_key=idempotency_key, **kwargs
            )
        return ToolResult.model_validate_json(operations[idempotency_key].model_dump_json())

    options["admitted_effect_invoke"] = host_idempotency
    first = type(source)(**options).create(CONTRACT, authority=AUTHORITY, idempotency_key=" key ")
    fresh = type(source)(**{**options, "now": lambda: NOW + timedelta(seconds=1)})
    assert fresh.create(CONTRACT, authority=AUTHORITY, idempotency_key=" key ") == first
    assert [key for key, _ in calls] == [" key ", " key "]
    assert calls[0][1].tool_call_id == calls[1][1].tool_call_id
    assert len(operations) == 1
    assert sum(c["toolName"] == "dataset.snapshot.create" for c in wire.calls) == 1
    distinct = type(source)(**options)
    distinct.create(CONTRACT, authority=AUTHORITY, idempotency_key="key")
    assert [key for key, _ in calls] == [" key ", " key ", "key"]
    assert calls[2][1].tool_call_id != calls[0][1].tool_call_id
    assert len(operations) == 2
    assert sum(c["toolName"] == "dataset.snapshot.create" for c in wire.calls) == 2


def test_foreign_result_id_is_refused():
    def foreign(call, context, **kwargs):
        return ready(call, context, **kwargs).model_copy(
            update={"tool_call_id": new_tool_call_id()}
        )

    host = invocation(foreign)
    with pytest.raises(CoverageRefusedError, match="upstream_not_ready"):
        host.call("create", {}, AUTHORITY, host.budget(AUTHORITY), "admitted-key")


@pytest.mark.parametrize("key", [None, "", " \t\n", 1, True, b"key", "k" * 513])
def test_bad_or_missing_key_refuses_before_host(key):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid key reached Host invocation")

    host = invocation(forbidden)
    budget = host.budget(AUTHORITY)
    with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
        host.call("create", {}, AUTHORITY, budget, key)
    assert budget.calls == 0


def test_raw_key_canonical_arguments_and_process_time_independence():
    host = invocation(ready)
    args = {"scope": {"b": 2, "a": 1}, "items": ["中文", "two"]}
    first = host.call("create", args, AUTHORITY, host.budget(AUTHORITY), " key ")["call_id"]
    fresh = invocation(ready, later=1)
    reordered = {"items": ["中文", "two"], "scope": {"a": 1, "b": 2}}
    assert (
        fresh.call("create", reordered, AUTHORITY, fresh.budget(AUTHORITY), " key ")["call_id"]
        == first
    )
    assert (
        fresh.call("create", reordered, AUTHORITY, fresh.budget(AUTHORITY), "key")["call_id"]
        != first
    )
    script = (
        "import sys; "
        "from agent_core.domain.host_authority import HostContextEnvelope; "
        "from tests.agent_integrations.test_coverage_snapshot_effect_replay "
        "import create_id; "
        "print(create_id(authority=HostContextEnvelope.model_validate_json(sys.argv[1]), later=2))"
    )
    other_process = subprocess.run(
        [sys.executable, "-c", script, AUTHORITY.model_dump_json()],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert other_process.stdout.strip() == create_id()


@pytest.mark.parametrize(
    "update",
    [
        {"namespace_id": "other"},
        {"host_app_id": "other"},
        {"workspace_ref": "other"},
        {"origin": "https://other.example"},
        {"grant_id": "other"},
        {"policy_version": "2"},
        {"expires_at": NOW + timedelta(hours=2)},
        {"scopes": ["history.read", "history.snapshot.write", "extra"]},
        {"limits": {**AUTHORITY.limits.model_dump(), "max_model_tokens": 101}},
        {
            "resource_refs": [
                *AUTHORITY.model_dump(mode="json")["resource_refs"],
                {"type": "other", "id": "extra"},
            ]
        },
    ],
)
def test_full_host_context_changes_identity(update):
    changed = HostContextEnvelope.model_validate({**AUTHORITY.model_dump(), **update})
    assert create_id(authority=changed) != create_id()


def test_bound_context_separately_changes_identity():
    changed = AUTHORITY.model_copy(update={"grant_id": "other"})
    first = invocation(ready)
    second = invocation(ready, authority=changed)
    assert first.call("create", {}, AUTHORITY, first.budget(AUTHORITY), "key") != second.call(
        "create", {}, AUTHORITY, second.budget(AUTHORITY), "key"
    )


def test_key_manifest_history_and_actual_arguments_do_not_alias():
    baseline = create_id()
    assert create_id(key="other-key") != baseline
    payload = frozen_manifest().to_payload()
    payload.pop("manifestDigest")
    payload["workloadIdentity"] = "other-worker"
    assert create_id(manifest=HostToolManifest.from_payload(payload)) != baseline
    changed = HostContextEnvelope.model_validate(
        {**AUTHORITY.model_dump(), "resource_refs": [{"type": "trench.history", "id": "other"}]}
    )
    assert create_id(authority=changed, history_ref="other") != baseline
    host = invocation(ready)
    for args in ({"scope": "other"}, {"history_ref": "other"}, {"items": [1, 2]}):
        assert (
            host.call("create", args, AUTHORITY, host.budget(AUTHORITY), "admitted-key")["call_id"]
            != baseline
        )


@pytest.mark.parametrize("name", ["get", "page", "read"])
def test_read_ids_remain_unique(name):
    ids = []
    for _ in range(2):
        host = invocation(ready)
        ids.append(host.call(name, {}, AUTHORITY, host.budget(AUTHORITY))["call_id"])
        ids.append(host.call(name, {}, AUTHORITY, host.budget(AUTHORITY))["call_id"])
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize(
    "output", ["Host Effect reconciled from its durable receipt.", '{"status":"ready"}']
)
def test_generic_reconciled_receipt_cannot_supply_descriptor(output):
    source, wire, options = setup_source()

    def reconciled(call, context, **kwargs):
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
            metadata={"business_outcome": "applied", "reason": "host_receipt_reconciled"},
        )

    fresh = type(source)(**{**options, "admitted_effect_invoke": reconciled})
    with pytest.raises(CoverageRefusedError):
        fresh.create(CONTRACT, authority=AUTHORITY, idempotency_key="key")
    assert wire.calls == []


def test_v1_typed_source_ref_preserves_legacy_create_identity():
    from agent_core.domain.host_authority import HostResourceRef

    old = invocation(ready)
    typed = invocation(ready)
    from agent_integrations.coverage_snapshot_invocation import CoverageInvocation

    typed = CoverageInvocation(
        authority=AUTHORITY,
        source_ref=HostResourceRef(type="trench.history", id="history"),
        manifest=typed.manifest,
        invoke=ready,
        admitted_effect_invoke=ready,
        now=lambda: NOW,
    )
    args = {"scope": "scope"}
    assert old.call("create", args, AUTHORITY, old.budget(AUTHORITY), "key") == typed.call(
        "create", args, AUTHORITY, typed.budget(AUTHORITY), "key"
    )
