"""Structured display evidence survives Host metadata redaction, not arbitrary dictionaries."""

from copy import deepcopy

import pytest
from agent_core.contracts.public_output import PublicReadFacts
from agent_core.domain.tools import ToolCallStatus
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolTransportResponse,
    HostWorkloadIdentity,
)
from agent_integrations.host_tools.gateway import _safe_metadata

from tests.agent_core.test_public_output import verified_facts
from tests.agent_integrations.test_host_tools import (
    _context,
    _FakeTransport,
    _tool_call,
    _tool_payload,
)


def test_signed_scoped_host_invocation_retains_strict_public_facts():
    facts = verified_facts("Read 20 records; this is a partial sample, not complete coverage.")
    transport = _FakeTransport(
        [
            HostToolTransportResponse(
                200,
                {
                    "workloadIdentity": "trench-worker",
                    "tools": [_tool_payload()],
                },
            ),
            HostToolTransportResponse(
                200,
                {
                    "output": "authorized event data",
                    "metadata": {"public_facts": facts, "secret": "drop", "arbitrary": {"a": "b"}},
                },
            ),
        ]
    )
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
    )
    context = _context()
    result = gateway.invoke(
        _tool_call(), context, idempotency_key="invoke-1", manifest=gateway.discover(context)
    )
    assert result.status is ToolCallStatus.EXECUTED
    retained = PublicReadFacts.model_validate(result.metadata["public_facts"])
    assert retained.summary == facts["summary"]
    assert retained.record_refs[0].event_id == "event-1"
    assert retained.evidence_basis == "verified_result"
    assert "secret" not in result.metadata and "arbitrary" not in result.metadata
    assert result.receipt.scopes == ("trench:event:read",)


@pytest.mark.parametrize("defect", ["private", "unbounded", "incomplete", "forged_bool", "scope"])
def test_invalid_structured_facts_do_not_cross_metadata_boundary(defect):
    facts = deepcopy(verified_facts("Partial authorized records."))
    if defect == "private":
        facts["authorization"] = "must-not-retain"
    elif defect == "unbounded":
        facts["summary"] = "x" * 1201
    elif defect == "incomplete":
        facts["query_completed"] = False
    elif defect == "forged_bool":
        facts["query_completed"] = 1
    else:
        facts["applied_scope"] = {"kind": "unverified"}
    assert _safe_metadata({"public_facts": facts, "trace_id": "trace-1"}) == {"trace_id": "trace-1"}
