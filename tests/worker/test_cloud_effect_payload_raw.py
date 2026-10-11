"""Original persisted request bytes must be checked before any lossy decoding."""

import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from zebra_agent_worker.cloud_effect_payloads import CloudEffectPayloadCoordinator
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator

from tests.agent_tools.test_effect_exact import setup_gateway
from tests.agent_tools.test_effect_guard import _call
from tests.worker.test_cloud_effect_payloads import _Artifacts


@pytest.mark.parametrize("route", ["local", "cloud"])
@pytest.mark.parametrize("fault", [
    "extra", "numeric_name", "string_arguments", "provider_extra",
    "naive_time", "legacy_valid",
])
def test_raw_request_is_validated_before_claim_or_transport(route, fault):
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    scheduled = guarded._schedule(call)
    uri = f"artifact://{uuid4()}"
    dispatch.pending = scheduled.model_copy(update={"payload_artifact_ref": uri})
    dispatch.stored = dispatch.pending
    raw = call.model_dump(mode="json")
    if fault == "extra":
        raw["unsupported"] = True
    elif fault == "numeric_name":
        raw["name"] = 123
    elif fault == "string_arguments":
        raw["arguments"] = "{}"
    elif fault == "provider_extra":
        raw["provider_call_id"] = {"unsupported": True}
    elif fault == "naive_time":
        raw["created_at"] = call.created_at.replace(tzinfo=None).isoformat()
    encoded = json.dumps(raw).encode()
    if route == "local":
        guarded._artifacts = SimpleNamespace(read_payload_bytes=lambda _: encoded)
        guarded._effect_payloads = None
    else:
        guarded._effect_payloads = CloudEffectPayloadCoordinator(
            guarded._execution_session_id,
            cast(CloudToolOutputArtifactCoordinator, _Artifacts(encoded)),
            cast(Any, dispatch),
        )
    before = dispatch.pending.model_dump()
    if fault == "legacy_valid":
        assert guarded.execute_exact(call).tool_call_id == call.tool_call_id
        assert gateway.calls == dispatch.claims == 1
    else:
        with pytest.raises(ValueError):
            guarded.execute_exact(call)
        assert gateway.calls == dispatch.claims == 0
        assert dispatch.pending.model_dump() == before
        assert dispatch.uncertain == dispatch.failed_no_effect == 0
