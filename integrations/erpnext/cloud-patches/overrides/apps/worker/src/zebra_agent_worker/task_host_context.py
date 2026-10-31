from __future__ import annotations

import json

from agent_core.domain.events import EventType, SessionEvent
from agent_core.harness.task_contracts import (
    TaskAcceptanceContract,
    infer_task_contract,
    parse_task_contract,
)
from agent_core.ports.context_compiler import RuntimeEvidenceInput


def _host_run_context(
    events: list[SessionEvent], *, fallback_goal: str
) -> tuple[tuple[RuntimeEvidenceInput, ...], TaskAcceptanceContract]:
    """Recover bounded AG-UI Host context from the durable accepted command."""

    evidence: list[RuntimeEvidenceInput] = []
    contract = infer_task_contract(fallback_goal)
    for event in reversed(events):
        if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
            continue
        raw_payload = event.payload.get("payload")
        raw_input = raw_payload.get("input") if isinstance(raw_payload, dict) else None
        raw_context = raw_input.get("context") if isinstance(raw_input, dict) else None
        if not isinstance(raw_context, list):
            continue
        for item in raw_context[:12]:
            if not isinstance(item, dict):
                continue
            description = item.get("description")
            value = item.get("value")
            if not isinstance(description, str) or not description.strip():
                continue
            if not isinstance(value, str) or not value.strip() or len(value) > 32_000:
                continue
            if description == "Agent task contract":
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        contract = parse_task_contract(parsed, fallback_goal=fallback_goal)
                except (ValueError, TypeError, json.JSONDecodeError):
                    contract = infer_task_contract(fallback_goal)
                continue
            evidence.append(
                RuntimeEvidenceInput(
                    kind="host_context",
                    summary=description.strip()[:256],
                    details=(value.strip(),),
                    metadata={"source": "ag_ui_context"},
                )
            )
        break
    return tuple(evidence), contract
