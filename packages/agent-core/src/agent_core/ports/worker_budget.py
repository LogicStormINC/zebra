"""Task-wide execution accounting ports; provider counters are trusted composition."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence


class WorkerBudgetError(ValueError):
    """Budget, proof or current execution boundary does not permit an effect."""


class ModelRequestOutcomeUnknown(RuntimeError):
    """A reserved model request lost its transport outcome before settlement."""


@dataclass(frozen=True)
class WorkerBudgetBinding:
    task_id: str
    session_id: SessionId
    binding_digest: str
    fence: LeaseFence
    attempt_number: int
    max_model_tokens: int
    max_runtime_seconds: int
    max_tool_calls: int

    def __post_init__(self) -> None:
        for value in (self.attempt_number, self.max_runtime_seconds):
            if type(value) is not int or value < 1:
                raise WorkerBudgetError("execution attempt and runtime must be positive integers")
        for value in (self.max_model_tokens, self.max_tool_calls):
            if type(value) is not int or value < 0:
                raise WorkerBudgetError("execution tokens/tools must be nonnegative integers")
        if len(self.binding_digest) != 64:
            raise WorkerBudgetError("binding digest must be canonical")


@dataclass(frozen=True)
class ModelRequestBudget:
    exact_body: bytes
    request_digest: str
    input_upper_bound: int
    output_cap: int
    counter_contract: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.exact_body, bytes)
            or not self.exact_body
            or len(self.exact_body) > 4 * 1024 * 1024
            or sha256(self.exact_body).hexdigest() != self.request_digest
        ):
            raise WorkerBudgetError("counter must inspect the exact bounded wire bytes")
        if (
            type(self.input_upper_bound) is not int
            or self.input_upper_bound < 0
            or type(self.output_cap) is not int
            or self.output_cap < 1
            or not self.counter_contract
            or len(self.counter_contract) > 256
        ):
            raise WorkerBudgetError("trusted input upper bound and output contract required")


@dataclass(frozen=True)
class ModelBudgetReservation:
    reservation_id: str
    request_digest: str
    input_upper_bound: int
    output_cap: int

    @property
    def token_bound(self) -> int:
        return self.input_upper_bound + self.output_cap


class WorkerBudgetStore(Protocol):
    def start(self, binding: WorkerBudgetBinding) -> None: ...
    def check_deadline(self, binding: WorkerBudgetBinding) -> None: ...
    def check(self, binding: WorkerBudgetBinding) -> float: ...
    def reserve_model(
        self, binding: WorkerBudgetBinding, request: ModelRequestBudget
    ) -> ModelBudgetReservation: ...
    def settle_model(
        self,
        binding: WorkerBudgetBinding,
        reservation: ModelBudgetReservation,
        raw_usage: object,
        receipt_id: str,
    ) -> None: ...
    def reserve_tool(self, binding: WorkerBudgetBinding, call_id: str) -> None: ...


def trusted_usage(raw: object, reservation: ModelBudgetReservation) -> tuple[int, int, int]:
    if not isinstance(raw, dict):
        raise WorkerBudgetError("missing provider usage leaves reservation unknown")
    prompt = raw.get("prompt_tokens", raw.get("input_tokens"))
    output = raw.get("completion_tokens", raw.get("output_tokens"))
    total = raw.get("total_tokens")
    if any(type(v) is not int or v < 0 for v in (prompt, output, total)):
        raise WorkerBudgetError("invalid provider usage leaves reservation unknown")
    prompt, output, total = cast(int, prompt), cast(int, output), cast(int, total)
    if (
        prompt + output != total
        or prompt > reservation.input_upper_bound
        or output > reservation.output_cap
        or total > reservation.token_bound
    ):
        raise WorkerBudgetError("invalid provider usage leaves reservation unknown")
    return prompt, output, total
