"""Structural Core validation only, not JWT, revocation or dispatch proof.

The caller must supply a verified Host context. Configured reviewer profiles,
capability composition and durable enforcement of model/time quotas are later
work; this validation does not admit an actually executable coverage Task.
"""

from datetime import datetime

from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_task_admission import (
    CoverageTaskAdmission,
    coverage_admission_input,
)
from agent_core.domain.host_authority import HostContextEnvelope


def validate_coverage_admission(
    value: object, *, host_context: object, now: datetime
) -> CoverageTaskAdmission:
    admission = CoverageTaskAdmission.model_validate(coverage_admission_input(value))
    if host_context is None:
        raise ValueError("coverage admission requires explicit Host context")
    host = HostContextEnvelope.model_validate(coverage_admission_input(host_context))
    if now.utcoffset() is None:
        raise ValueError("coverage admission clock must be timezone-aware")
    if host.expires_at is None or host.expires_at <= now:
        raise ValueError("coverage admission requires future Host expiry")
    source = admission.contract.source_definition
    host.require_scope(source.read_scope)
    host.require_scope(source.create_scope)
    resources = tuple(
        ref for ref in host.resource_refs if ref.resource_type == source.resource_type
    )
    if resources != (admission.source_resource,):
        raise ValueError("coverage admission requires exactly one matching source resource")
    if (
        admission.max_model_tokens > host.limits.max_model_tokens
        or admission.max_runtime_seconds > host.limits.max_runtime_seconds
    ):
        raise ValueError("coverage admission budget exceeds Host technical limits")
    if admission.contract.checks != (semantic_check(admission.model_profile).contract_check,):
        raise ValueError("coverage admission requires exactly the published semantic check")
    return admission
