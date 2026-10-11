"""Strict create and schedule requests cannot fall through to ordinary execution."""

from copy import deepcopy

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_binding import _compose_admission
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session
from zebra_agent_api.task_schedule_template import validate_schedule_template

from tests.agent_core.test_coverage_task_admission import admission


def test_valid_strict_create_and_schedule_refuse_before_side_effects():
    payload = {"prompt": "review", "coverage_admission": admission().model_dump(mode="json")}
    create = parse_create_session_payload(payload)
    # Unconfigured sentinels prove no app/request/storage/connector access occurs.
    scheduled = validate_schedule_template(None, None, payload, None)
    assert isinstance(create, ApiResponse) and scheduled == create
    assert create.status_code == 503
    assert create.body == {
        "status": "coverage_unsupported", "reason": "strict_worker_not_ready"
    }


def test_invalid_strict_input_never_becomes_an_ordinary_request():
    valid = admission().model_dump(mode="json")
    forged = deepcopy(valid)
    forged["max_model_calls"] = True
    typed = admission().model_copy(update={"unknown": True})
    for raw in (None, {}, "exhaustive", forged, valid | {"unknown": True}, typed):
        result = parse_create_session_payload({"prompt": "review", "coverage_admission": raw})
        assert isinstance(result, ApiResponse) and result.status_code == 400
        assert result.body == {
            "status": "invalid_request", "reason": "coverage_admission is invalid"
        }


def test_ordinary_create_payload_stays_unchanged():
    result = parse_create_session_payload({"prompt": "review"})
    assert not isinstance(result, ApiResponse)
    assert result["prompt"] == "review" and "coverage_admission" not in result


def test_strict_app_preflight_precedes_idempotency_hash_replay_and_reconciliation():
    # No initialized stores: even an existing key must not inspect/replay a receipt,
    # hash forged typed input, reconcile an old response, or queue ordinary work.
    app = object.__new__(ZebraAgentApi)
    for raw, status in (
        (admission().model_dump(mode="json"), 503),
        (admission().model_copy(update={"unknown": True}), 400),
        (None, 400),
    ):
        response = app.create_session(
            {"prompt": "review", "coverage_admission": raw},
            idempotency_key="existing-receipt",
        )
        assert response.status_code == status


def test_direct_adapters_refuse_strict_identity_before_manifest_or_storage():
    for raw, status in (
        (admission().model_dump(mode="json"), 503),
        (admission().model_copy(update={"unknown": True}), 400),
        (None, 400),
    ):
        payload = {"prompt": "review", "coverage_admission": raw}
        expected = parse_create_session_payload(payload)
        # No usable API/stores/Host: strict input must return before reaching any.
        composed = _compose_admission(None, object(), payload, "existing-key")
        queued = create_queued_session(None, payload)
        assert isinstance(composed, ApiResponse) and composed == expected == queued
        assert composed.status_code == status
