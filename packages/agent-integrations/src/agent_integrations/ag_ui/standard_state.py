"""Versioned task-wide state for the opt-in standard producer."""

import json
from dataclasses import dataclass, field
from re import fullmatch
from typing import Any
from uuid import UUID

from ag_ui.core import TokenUsage
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.ports.task_projection_checkpoints import MAX_CHECKPOINT_BYTES

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.projection_state import ProjectionState

MAX_STANDARD_STATE_BYTES = MAX_CHECKPOINT_BYTES // 32
PUBLIC_PAUSE_DIAGNOSTICS = frozenset(
    {
        "model_call_budget_exhausted",
        "tool_call_budget_exhausted",
        "execution_storage_contention",
        "execution_storage_unavailable",
        "execution_authority_unavailable",
        "plugin_authority_unavailable",
        "workspace_changed",
        "execution_paused",
        "delivery_incomplete",
    }
)


@dataclass(slots=True)
class StandardProjectionState(ProjectionState):
    protocol_run_id: str | None = None
    public_execution: dict[str, Any] = field(default_factory=dict)
    continuation_id: str | None = None
    previous_protocol_run_id: str | None = None
    # Only public identities/accounting and observed lifecycle membership live here.
    pending_tools: dict[str, str] = field(default_factory=dict)
    executing_tools: set[str] = field(default_factory=set)
    active_step: str | None = None
    active_step_content: str | None = None
    active_step_name: str | None = None
    active_step_started_at: int | None = None
    child_epoch_cut: bool = False
    seen_usage: set[str] = field(default_factory=set)
    usage: list[dict[str, Any]] = field(default_factory=list)
    usage_unknown: bool = False
    subagent_usage_unknown: bool = False
    commentary_open: dict[str, str] = field(default_factory=dict)
    commentary_offsets: dict[str, int] = field(default_factory=dict)
    publications: set[str] = field(default_factory=set)
    children: dict[str, dict[str, str]] = field(default_factory=dict)

    def snapshot(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "protocol_run_id": self.protocol_run_id,
                "public_execution": self.public_execution,
                "continuation_id": self.continuation_id,
                "previous_protocol_run_id": self.previous_protocol_run_id,
                "started": self.started,
                "turn_finished": self.turn_finished,
                "pending_tools": self.pending_tools,
                "executing_tools": sorted(self.executing_tools),
                "active_step": self.active_step,
                "active_step_content": self.active_step_content,
                "active_step_name": self.active_step_name,
                "active_step_started_at": self.active_step_started_at,
                "seen_usage": [],
                "usage": self.usage,
                "usage_unknown": self.usage_unknown,
                "subagent_usage_unknown": self.subagent_usage_unknown,
                "publications": [],
                "commentary_offsets": self.commentary_offsets,
                "commentary_open": self.commentary_open,
                "children": self.children,
                "child_epoch_cut": self.child_epoch_cut,
                "coverage_runs": {
                    key: {
                        k: v.model_dump(mode="json") if isinstance(v, CoverageRunBinding) else v
                        for k, v in run.items()
                    }
                    for key, run in self.coverage_runs.items()
                },
            },
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def restore(cls, value: str) -> "StandardProjectionState":
        try:
            if len(value.encode()) > MAX_STANDARD_STATE_BYTES:
                raise ValueError("state budget")
            data = json.loads(value)
            cls._validate_snapshot(data)
            data.pop("version")
            for key in ("executing_tools", "seen_usage", "publications"):
                data[key] = set(data[key])
            for run in data["coverage_runs"].values():
                run["_binding"] = CoverageRunBinding.model_validate(run["_binding"])
            return cls(**data)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise AgUiProjectionError("invalid standard checkpoint state") from None

    @classmethod
    def _validate_snapshot(cls, data: Any) -> None:
        def require(condition: bool) -> None:
            if not condition:
                raise ValueError("invalid standard state shape")

        expected = json.loads(cls().snapshot())
        require(isinstance(data, dict) and data.keys() == expected.keys())
        for key, default in expected.items():
            item = data[key]
            if default is None:
                require(
                    item is None
                    or (
                        type(item) is int
                        if key == "active_step_started_at"
                        else isinstance(item, str) and bool(item.strip())
                    )
                )
            else:
                require(type(item) is type(default))
        require(data["version"] == 1 and data["started"])
        require(bool(fullmatch(r"agui:[0-9a-f]{64}", data["protocol_run_id"] or "")))
        require(str(UUID(data["continuation_id"])) == data["continuation_id"])
        previous = data["previous_protocol_run_id"]
        require(previous is None or bool(fullmatch(r"agui:[0-9a-f]{64}", previous)))
        require(not data["seen_usage"] and not data["publications"])
        for key in ("pending_tools", "commentary_open"):
            require(
                all(
                    isinstance(k, str) and k and isinstance(v, str) and v
                    for k, v in data[key].items()
                )
            )
        require(
            all(
                isinstance(k, str) and k and type(v) is int and v >= 1
                for k, v in data["commentary_offsets"].items()
            )
        )
        require(data["commentary_open"].keys() <= data["commentary_offsets"].keys())
        require(all(isinstance(v, str) and v for v in data["executing_tools"]))
        phase = data["public_execution"]
        require(phase.keys() <= {"status", "diagnostic", "openInterruptIds"})
        require(
            not phase
            or phase.get("status")
            in {
                "running",
                "resuming",
                "waiting_input",
                "paused",
                "completed",
                "cancelled",
                "failed",
            }
        )
        if "diagnostic" in phase:
            require(phase["diagnostic"] in PUBLIC_PAUSE_DIAGNOSTICS)
        if "openInterruptIds" in phase:
            require(
                isinstance(phase["openInterruptIds"], list)
                and all(
                    isinstance(v, str) and v.startswith(("approval:", "clarification:"))
                    for v in phase["openInterruptIds"]
                )
            )
        step = data["active_step"]
        require(
            all(
                data[k] is None
                for k in ("active_step_content", "active_step_name", "active_step_started_at")
            )
            if step is None
            else all(
                data[k] is not None
                for k in ("active_step_content", "active_step_name", "active_step_started_at")
            )
        )
        for child in data["children"].values():
            require(
                isinstance(child, dict)
                and set(child)
                in (
                    {"invocation", "call", "name"},
                    {"invocation", "call", "name", "sequence", "session"},
                )
                and all(isinstance(v, str) and v for v in child.values())
            )
            if "sequence" in child:
                require(bool(fullmatch(r"[0-9]+", child["sequence"])))
                require(str(UUID(child["session"])) == child["session"])
        usage_keys = {field.alias or name for name, field in TokenUsage.model_fields.items()}
        for usage in data["usage"]:
            require(isinstance(usage, dict) and usage.keys() <= usage_keys)
            TokenUsage.model_validate(usage, strict=True)
        coverage_keys = {
            "_binding",
            "schema_version",
            "run_id",
            "snapshot_id",
            "manifest_digest",
            "enumerated_records",
            "expected_units",
            "accepted_units",
            "phase",
            "expires_at",
            "source_watermark",
        }
        for run_id, run in data["coverage_runs"].items():
            require(isinstance(run, dict) and run.keys() == coverage_keys)
            binding = CoverageRunBinding.model_validate(run["_binding"])
            require(
                run_id == run["run_id"] == binding.run_id
                and type(run["schema_version"]) is int
                and run["schema_version"] == 1
            )
            require(
                all(
                    type(run[k]) is int and run[k] >= 0
                    for k in (
                        "enumerated_records",
                        "expected_units",
                        "accepted_units",
                        "source_watermark",
                    )
                )
            )
            require(run["accepted_units"] <= run["expected_units"])
            require(run["phase"] in {"processing", "cancelled", "certified"})
            require(
                run["snapshot_id"] == binding.snapshot.snapshot_id
                and run["manifest_digest"] == binding.snapshot.manifest_digest
                and run["expires_at"] == binding.snapshot.expires_at.isoformat()
            )

    def begin(self, run_id: str, anchor: str) -> None:
        self.previous_protocol_run_id = self.protocol_run_id
        self.protocol_run_id = run_id
        self.continuation_id = anchor
        self.started = False
        self.turn_finished = False
        self.seen_usage.clear()
        self.usage.clear()
        self.usage_unknown = False
        self.subagent_usage_unknown = bool(self.children) or any(
            self.pending_tools.get(call) == "agent.research" for call in self.executing_tools
        )
        self.publications.clear()
        # Delegation identities persist, but are never treated as child access grants.
