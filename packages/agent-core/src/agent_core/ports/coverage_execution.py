"""Explicit durable executor boundary; no successful in-memory fallback."""

from collections.abc import Callable
from typing import Protocol

from agent_core.domain.coverage_execution import CoverageExecutionBudget, CoverageObservation
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    CoverageUnitKey,
)
from agent_core.domain.leases import LeaseFence
from agent_core.ports.coverage import CoverageCommitPort


class CoverageExecutionStorePort(CoverageCommitPort, Protocol):
    def bind(self, binding: CoverageRunBinding, *, fence: LeaseFence) -> int: ...

    def missing_units(
        self, namespace: str, run_id: str, *, limit: int = 100, after_ordinal: int = -1
    ) -> tuple[tuple[int, CoverageUnitKey], ...]: ...

    def accepted_for_record(
        self, namespace: str, run_id: str, record_id: str, *, check_id: str | None = None
    ) -> tuple[AcceptedCoverageUnit, ...]: ...

    def reserve_attempt(
        self,
        binding: CoverageRunBinding,
        key: CoverageUnitKey,
        *,
        input_bytes: int,
        budget: CoverageExecutionBudget,
        fence: LeaseFence,
    ) -> int: ...

    def counts(self, namespace: str, run_id: str) -> tuple[int, int]: ...


class CoverageCheckRunnerPort(Protocol):
    def run(
        self,
        key: CoverageUnitKey,
        bodies: dict[str, str],
        *,
        prior: tuple[CoverageObservation, ...],
    ) -> CoverageObservation: ...


class CoveragePublicationStorePort(Protocol):
    def accepted_page(
        self, namespace: str, run_id: str, *, limit: int = 100, after_ordinal: int = -1
    ) -> tuple[tuple[int, AcceptedCoverageUnit], ...]: ...

    def certify(
        self,
        namespace: str,
        run_id: str,
        *,
        report_ref: str,
        report_digest: str,
        fence: LeaseFence,
        check_authority: Callable[[], None],
    ) -> CoverageCertificate: ...
