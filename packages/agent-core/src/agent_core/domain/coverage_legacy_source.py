"""Explicit v1 source compatibility; new admissions freeze their own declaration."""

from agent_core.domain.coverage_contracts import CoverageSourceDefinition

LEGACY_COVERAGE_SOURCE = CoverageSourceDefinition(
    resource_type="trench.history", read_scope="history.read", create_scope="history.snapshot.write"
)
