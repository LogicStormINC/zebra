from dataclasses import dataclass

from agent_core.ports.context_compiler import RuntimeEvidenceInput


@dataclass(frozen=True)
class RetryPlanHint:
    summary: str
    focus: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    accepted_constraints: tuple[str, ...] = ()
    prior_tool_outputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("retry plan hint summary must not be blank")
        _ensure_nonblank("focus", self.focus)
        _ensure_nonblank("blockers", self.blockers)
        _ensure_nonblank("accepted_constraints", self.accepted_constraints)
        _ensure_nonblank("prior_tool_outputs", self.prior_tool_outputs)


def build_retry_plan_hint(
    runtime_evidence: tuple[RuntimeEvidenceInput, ...],
) -> RetryPlanHint:
    if not runtime_evidence:
        return RetryPlanHint(summary="initial attempt: no prior runtime evidence")

    focus: list[str] = []
    blockers: list[str] = []
    accepted_constraints: list[str] = []
    prior_tool_outputs: list[str] = []

    for evidence in runtime_evidence:
        if evidence.kind == "planner_summary":
            focus.append(evidence.summary)
            continue
        if evidence.kind == "verifier_summary":
            if bool((evidence.metadata or {}).get("passed")):
                accepted_constraints.append(evidence.summary)
            else:
                blockers.append(evidence.summary)
            continue
        if evidence.kind == "tool_status":
            _append_failed_tool_status(blockers, evidence.summary)
            continue
        if evidence.kind == "tool_output_summary":
            prior_tool_outputs.append(evidence.summary)

    return RetryPlanHint(
        summary=_summarize_retry_plan(
            focus=tuple(focus),
            blockers=tuple(blockers),
            accepted_constraints=tuple(accepted_constraints),
            prior_tool_outputs=tuple(prior_tool_outputs),
        ),
        focus=tuple(focus),
        blockers=tuple(blockers),
        accepted_constraints=tuple(accepted_constraints),
        prior_tool_outputs=tuple(prior_tool_outputs),
    )


def _summarize_retry_plan(
    *,
    focus: tuple[str, ...],
    blockers: tuple[str, ...],
    accepted_constraints: tuple[str, ...],
    prior_tool_outputs: tuple[str, ...],
) -> str:
    if blockers:
        return "retry should address verifier or tool failures before repeating prior steps"
    if accepted_constraints:
        return "retry can preserve verified behavior while continuing"
    if focus:
        return "retry should continue from prior planner guidance"
    if prior_tool_outputs:
        return "retry should inspect prior tool output before selecting the next action"
    return "retry has prior evidence but no actionable planner or verifier signal"


def _append_failed_tool_status(blockers: list[str], status: str) -> None:
    normalized = status.strip().lower()
    if normalized in {"executed", "completed", "succeeded", "success"}:
        return
    blockers.append(f"previous tool status: {status}")


def _ensure_nonblank(field_name: str, values: tuple[str, ...]) -> None:
    for value in values:
        if not value.strip():
            raise ValueError(f"retry plan hint {field_name} must not contain blanks")
