"""Pure rebuild routing/retention regression; native retention tests remain unchanged."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType
from agent_storage.postgres import coverage, coverage_model_source
from agent_storage.postgres.coverage import PostgresCoverageStore

from tests.agent_core.test_coverage_contracts import contract, records


def rebuild_case(monkeypatch, *, strict=False, certified=False):
    manifest_records = records()
    binding = SimpleNamespace(session_id="session", contract=contract())
    rows = [
        {
            "event_type": EventType.COVERAGE_MANIFEST_COMMITTED.value,
            "sequence": 1,
            "session_id": binding.session_id,
            "payload": {"expected_count": 1},
        },
        {
            "event_type": EventType.COVERAGE_MODEL_BUDGET_INITIALIZED.value,
            "sequence": 2,
            "session_id": binding.session_id,
            "payload": {},
        },
    ]
    if strict or certified:
        rows.append(
            {
                "event_type": (
                    EventType.COVERAGE_REPORT_CERTIFIED
                    if certified
                    else EventType.COVERAGE_BATCH_ACCEPTED
                ).value,
                "sequence": 3,
                "session_id": binding.session_id,
                "payload": {},
            }
        )
    calls = []
    connection = SimpleNamespace(execute=lambda *a: calls.append("delete"))
    store = object.__new__(PostgresCoverageStore)
    store._database = SimpleNamespace(connect=lambda: nullcontext(connection))
    store._deployment = "deployment"
    store._artifacts = object()
    store._model_observation_deriver = None
    store._rebuild_budget = lambda *_: calls.append("final_budget")
    monkeypatch.setattr(coverage, "iter_run_events", lambda *_, **__: iter(rows))
    monkeypatch.setattr(coverage, "binding_from_event", lambda *_: binding)
    monkeypatch.setattr(coverage, "read_manifest", lambda *_: manifest_records)
    monkeypatch.setattr(coverage, "validate_event_fence", lambda *_: None)
    monkeypatch.setattr(coverage, "lock_run", lambda *_: None)
    monkeypatch.setattr(
        coverage,
        "SessionEvent",
        SimpleNamespace(
            model_validate=lambda row: SimpleNamespace(
                **{**row, "event_type": EventType(row["event_type"])}
            ),
        ),
    )
    monkeypatch.setattr(coverage, "replay_request", lambda *_: calls.append("request"))
    monkeypatch.setattr(coverage, "seed_run", lambda *_: calls.append("seed") or 1)
    monkeypatch.setattr(coverage, "project_watermark", lambda *_, **__: None)
    return store, binding, manifest_records, calls


@pytest.mark.parametrize("expired", [False, True])
def test_budget_only_rebuild_replays_exact_keys_and_keeps_final_retention(monkeypatch, expired):
    store, binding, manifest_records, calls = rebuild_case(monkeypatch)
    deadline = datetime.now(UTC) + timedelta(seconds=1)

    def replay(connection, deployment, actual_binding, **kwargs):
        assert actual_binding is binding and kwargs["rebuild"] is True
        assert kwargs["artifacts"] is store._artifacts
        assert kwargs["source_keys"] == set(expected_units(binding.contract, manifest_records))
        kwargs["retention_deadlines"].append(deadline)
        calls.append("replay")
        return None, {}

    def forbidden(*_, **__):
        raise AssertionError("budget-only rebuild must not require acceptance manifest lifecycle")

    def final_retention(connection, deadlines):
        assert deadlines == [deadline] and calls[-1] == "final_budget"
        calls.append("retention")
        if expired:
            raise ValueError("original checkpoint retention expired")

    monkeypatch.setattr(coverage_model_source, "replay_model", replay)
    monkeypatch.setattr(coverage, "_ModelVerification", forbidden)
    monkeypatch.setattr(coverage, "check_checkpoint_retention", final_retention)
    if expired:
        with pytest.raises(ValueError, match="retention expired"):
            store.rebuild("namespace", "run")
    else:
        assert store.rebuild("namespace", "run") == 2
    assert calls == ["replay", "delete", "seed", "final_budget", "retention"]


@pytest.mark.parametrize("certified", [False, True])
def test_accepted_or_certified_rebuild_still_requires_strict_proof_before_mutation(
    monkeypatch,
    certified,
):
    store, _, _, calls = rebuild_case(monkeypatch, strict=True, certified=certified)

    def strict(*_, **kwargs):
        assert kwargs["rebuild"] is True
        raise ValueError("strict accepted proof unavailable")

    monkeypatch.setattr(coverage, "_ModelVerification", strict)
    with pytest.raises(ValueError, match="strict accepted proof"):
        store.rebuild("namespace", "run")
    assert "delete" not in calls and "seed" not in calls


def test_budget_only_original_proof_failure_precedes_projection_mutation(monkeypatch):
    store, _, _, calls = rebuild_case(monkeypatch)
    failure = ValueError("original checkpoint unavailable")

    def replay(*_, **kwargs):
        assert kwargs["rebuild"] is True
        raise failure

    monkeypatch.setattr(coverage_model_source, "replay_model", replay)
    with pytest.raises(ValueError) as caught:
        store.rebuild("namespace", "run")
    assert caught.value is failure and calls == []
