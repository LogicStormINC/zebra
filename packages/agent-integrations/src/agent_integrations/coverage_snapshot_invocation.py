"""Explicit signed gateway capabilities and per-operation authority/call budgets."""

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolIdempotency, ToolResult, ToolRisk

from agent_integrations.host_tools.contracts import HostToolManifest


class HostCoverageInvoke(Protocol):
    """HostToolGateway.invoke signature; composition supplies its signed invocation.

    The separately supplied admitted_effect_invoke must run inside an already
    admitted Effect; a raw gateway alone does not confer write admission.
    """

    def __call__(
        self,
        tool_call: ToolCall,
        context: HostContextEnvelope,
        *,
        idempotency_key: str | None = None,
        required_resource: HostResourceRef | None = None,
        manifest: HostToolManifest | None = None,
    ) -> ToolResult: ...


class OperationBudget:
    def __init__(self, calls: int, seconds: float, clock: Callable[[], float]) -> None:
        self.maximum_calls = calls
        self.seconds = seconds
        self.clock = clock
        self.started = clock()
        self.calls = 0

    def check(self) -> None:
        elapsed = self.clock() - self.started
        if not math.isfinite(elapsed) or elapsed < 0 or elapsed >= self.seconds:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)

    def before_call(self) -> None:
        self.check()
        if self.calls >= self.maximum_calls:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        self.calls += 1


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class CoverageInvocation:
    def __init__(
        self,
        *,
        authority: HostContextEnvelope,
        history_ref: str,
        manifest: HostToolManifest | None,
        invoke: HostCoverageInvoke | None,
        admitted_effect_invoke: HostCoverageInvoke | None,
        max_calls: int = 2048,
        max_seconds: float = 60,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(max_calls) is not int or not 1 <= max_calls <= 2048:
            raise ValueError("max_calls must be in [1, 2048]")
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, int | float)
            or not math.isfinite(max_seconds)
            or not 0 < max_seconds <= 60
        ):
            raise ValueError("max_seconds must be in (0, 60]")
        if not history_ref or history_ref != history_ref.strip():
            raise ValueError("history_ref must be explicit and trimmed")
        self.bound = authority
        self.resource = HostResourceRef(type="trench.history", id=history_ref)
        # Round-trip pins and independently validates the frozen manifest digest.
        self.manifest = HostToolManifest.from_payload(manifest.to_payload()) if manifest else None
        self.invoke = invoke
        self.effect = admitted_effect_invoke
        self.max_calls = max_calls
        self.max_seconds = max_seconds
        self.now = now
        self.monotonic = monotonic

    def authority_check(self, authority: HostContextEnvelope, *, write: bool = False) -> None:
        current = self.now()
        if (
            current.utcoffset() is None
            or authority.host_app_id != self.bound.host_app_id
            or authority.namespace_id != self.bound.namespace_id
            or authority.workspace_ref != self.bound.workspace_ref
            or authority.origin != self.bound.origin
            or authority.expires_at is None
            or current >= authority.expires_at
            or self.resource not in authority.resource_refs
            or sum(
                resource.resource_type == "trench.history" for resource in authority.resource_refs
            )
            != 1
            or "history.read" not in authority.scopes
            or (write and "history.snapshot.write" not in authority.scopes)
        ):
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID)

    def budget(self, authority: HostContextEnvelope) -> OperationBudget:
        self.authority_check(authority)
        return OperationBudget(
            self.max_calls,
            min(self.max_seconds, authority.limits.max_runtime_seconds),
            self.monotonic,
        )

    def publication_time(
        self,
        authority: HostContextEnvelope,
        budget: OperationBudget,
        as_of: datetime,
        expires_at: datetime,
    ) -> datetime:
        budget.check()
        self.authority_check(authority)
        now = self.now()
        if not as_of <= now < expires_at:
            raise CoverageRefusedError(Reason.SNAPSHOT_EXPIRED)
        return now

    def call(
        self,
        name: str,
        arguments: dict[str, object],
        authority: HostContextEnvelope,
        budget: OperationBudget,
        key: str | None = None,
    ) -> dict[str, object]:
        write = name == "create"
        self.authority_check(authority, write=write)
        invoker = self.effect if write else self.invoke
        tool_name = "dataset.snapshot." + name
        contract = self.manifest.get(tool_name) if self.manifest else None
        if invoker is None or contract is None or self.manifest is None:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        rules = self.manifest.resource_bindings_for(tool_name)
        if (
            "history.read" not in contract.scopes
            or set(contract.scopes) - set(authority.scopes)
            or not any(
                rule.argument_pointer == "/history_ref"
                and rule.resource_type == "trench.history"
                and rule.required
                and rule.match_mode == "exact"
                for rule in rules
            )
            or (
                write
                and (
                    "history.snapshot.write" not in contract.scopes
                    or contract.risk != ToolRisk.WRITE
                    or contract.idempotency != ToolIdempotency.REQUIRED
                )
            )
            or (not write and contract.risk != ToolRisk.READ)
        ):
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        budget.before_call()
        call = ToolCall(
            tool_call_id=new_tool_call_id(),
            name=tool_name,
            arguments={"history_ref": self.resource.resource_id, **arguments},
            created_at=self.now(),
        )
        try:
            result = invoker(
                call,
                authority,
                idempotency_key=key,
                required_resource=self.resource,
                manifest=self.manifest,
            )
        finally:
            budget.check()
            self.authority_check(authority, write=write)
        if result.tool_call_id != call.tool_call_id or result.status != ToolCallStatus.EXECUTED:
            raw_reason = result.metadata.get("http_error_code", result.metadata.get("reason"))
            try:
                reason = (
                    Reason(raw_reason) if isinstance(raw_reason, str) else Reason.UPSTREAM_NOT_READY
                )
            except (TypeError, ValueError):
                reason = Reason.UPSTREAM_NOT_READY
            raise CoverageRefusedError(reason)
        maximum = min(contract.max_output_bytes, 131072, authority.limits.max_artifact_bytes)
        if len(result.output) > maximum or len(result.output.encode("utf-8")) > maximum:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        try:
            value = json.loads(
                result.output,
                object_pairs_hook=unique_object,
                parse_constant=lambda raw: (_ for _ in ()).throw(ValueError(raw)),
            )
            if not isinstance(value, dict):
                raise ValueError("expected object")
        except (ValueError, RecursionError) as exc:
            raise CoverageRefusedError(Reason.UNSUPPORTED) from exc
        if value.get("status") != "ready":
            raise CoverageRefusedError(Reason.UPSTREAM_NOT_READY)
        budget.check()
        return value
