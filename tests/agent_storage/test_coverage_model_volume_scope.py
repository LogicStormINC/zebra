"""Pure scoped lifecycle enumeration; global SQL bounds and exact retries remain."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_storage.postgres import coverage_model_source as source
from agent_storage.postgres.coverage_model_volume import preflight_original_volume

from tests.agent_core.test_coverage_model_budget import reservation
from tests.agent_core.test_coverage_task_admission import NOW


@pytest.fixture
def env(monkeypatch):
    receipts = []
    for index in range(3):
        reserved = reservation()
        key = reserved.key.model_copy(update={"record_id": f"record-{index}"})
        reserved = reserved.model_copy(update={"key": key, "reservation_key": f"call-{index}"})
        receipts.append(CoverageModelUsageReceipt(
            reservation=reserved, input_tokens=1, output_tokens=2, total_tokens=3,
            checkpoint_ref=f"artifact://00000000-0000-0000-0000-{index + 1:012d}",
            checkpoint_digest="c" * 64,
        ))
    rows = [
        {"receipt": receipt.model_dump(mode="json"), "sequence": index * 3 + 3,
         "reserved_sequence": index * 3 + 1,
         "reservation": receipt.reservation.model_dump(mode="json"), "size_bytes": 10}
        for index, receipt in enumerate(receipts)
    ]

    class Connection:
        def __init__(self):
            self.rows = rows
            self.volume = {"count": 7, "bytes": 10}
            self.sizes = {"count": 3, "unique_count": 3, "available": 3, "bytes": 30, "last": 9}
            self.pages, self.aggregates = [], []

        def execute(self, sql, params):
            if "octet_length" in sql or "count(DISTINCT sequence)" in sql:
                assert "jsonb[]" not in sql  # Global bounds must never inherit the scope.
                self.aggregates.append(sql)
                result = self.volume if "octet_length" in sql else self.sizes
                return SimpleNamespace(fetchone=lambda: result)
            assert "ORDER BY sequence LIMIT 100" in sql
            selected = self.rows
            if "jsonb[]" in sql:
                assert "->'key'=ANY(%s::jsonb[])" in sql
                assert "OR e.payload->'receipt'->'reservation'->>'reservation_key'=%s" in sql
                keys, candidate_key = params[4:6]
                keys = [key.obj for key in keys]
                selected = [row for row in selected if (
                    row["receipt"]["reservation"]["key"] in keys
                    or row["receipt"]["reservation"]["reservation_key"] == candidate_key
                )]
            cursor, upper = params[-2:]
            selected = [row for row in selected if cursor < row["sequence"] <= upper][:100]
            self.pages.append([row["sequence"] for row in selected])
            return SimpleNamespace(fetchall=lambda: deepcopy(selected))

    connection = Connection()
    monkeypatch.setattr(
        "agent_storage.postgres.coverage_model_volume.volume_summary", lambda *args: None,
    )
    lifecycle = Mock(side_effect=lambda *args, **kwargs: SimpleNamespace(
        reservation=SimpleNamespace(size_bytes=10, retained_until=NOW + timedelta(seconds=30))
    ))
    policy = Mock(return_value=SimpleNamespace(validation_mode="final_certification"))
    retention = Mock()
    monkeypatch.setattr(source, "task_policy", policy)
    monkeypatch.setattr(source, "checkpoint_source", lifecycle)
    monkeypatch.setattr(source, "check_checkpoint_retention", retention)
    monkeypatch.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", 40)
    return SimpleNamespace(
        connection=connection, receipts=receipts, lifecycle=lifecycle,
        policy=policy, retention=retention,
        binding=SimpleNamespace(session_id="session", namespace="namespace", run_id="run"),
    )


def preflight(env, **kwargs):
    return source.preflight_original_volume(env.connection, "deployment", env.binding, **kwargs)


@pytest.mark.parametrize("scope", ["legacy", "current", "empty"])
def test_enumeration_counts_and_retention_are_scoped_without_caching(env, scope):
    assert source.preflight_original_volume is preflight_original_volume
    keys = None if scope == "legacy" else (
        {env.receipts[1].reservation.key} if scope == "current" else set()
    )
    for _ in range(2):
        deadlines = []
        preflight(env, _incremental_keys=keys, retention_deadlines=deadlines)
        assert deadlines == ([] if scope == "empty" else [NOW + timedelta(seconds=30)])
        env.retention.assert_called_with(env.connection, deadlines)
    checked = [call.args[3] for call in env.lifecycle.call_args_list]
    assert checked == (
        env.receipts * 2 if scope == "legacy" else
        [env.receipts[1]] * 2 if scope == "current" else []
    )
    assert len(env.connection.aggregates) == 4
    assert env.policy.call_count == (0 if scope == "legacy" else 2)
    if scope == "empty":
        assert env.connection.pages == []


@pytest.mark.parametrize("mode", [None, "eager"])
def test_scope_requires_explicit_admission_before_any_volume_read(env, mode):
    env.policy.return_value = None if mode is None else SimpleNamespace(validation_mode=mode)
    with pytest.raises(ValueError, match="final_certification admission"):
        preflight(env, _incremental_keys=set())
    assert env.connection.aggregates == []


@pytest.mark.parametrize("mode", [None, "eager", "final_certification"])
def test_locked_chain_reuses_only_supplied_native_policy(env, mode):
    policy = None if mode is None else SimpleNamespace(validation_mode=mode)
    if mode == "final_certification":
        preflight(env, _incremental_keys=set(), _policy=policy)
        assert len(env.connection.aggregates) == 2
    else:
        with pytest.raises(ValueError, match="final_certification admission"):
            preflight(env, _incremental_keys=set(), _policy=policy)
        assert env.connection.aggregates == []
    env.policy.assert_not_called()
    preflight(env, _incremental_keys=set())
    env.policy.assert_called_once()


@pytest.mark.parametrize("scope", [None, set()])
@pytest.mark.parametrize(
    "damage", ["event_count", "event_bytes", "count", "available", "bytes", "duplicate"]
)
def test_global_bounds_refuse_before_any_lifecycle_enumeration(env, scope, damage):
    if damage.startswith("event_"):
        env.connection.volume[damage.removeprefix("event_")] = (
            400002 if damage == "event_count" else 41
        )
    else:
        field, value = {
            "count": ("count", 200001), "available": ("available", 2),
            "bytes": ("bytes", 41), "duplicate": ("unique_count", 2),
        }[damage]
        env.connection.sizes[field] = value
        if damage == "count":
            env.connection.sizes["unique_count"] = value
    with pytest.raises(ValueError):
        preflight(env, _incremental_keys=scope)
    env.lifecycle.assert_not_called()
    assert env.connection.pages == []


@pytest.mark.parametrize("retry", [True, False])
def test_candidate_is_included_even_with_empty_scope_and_counted_once(env, retry, monkeypatch):
    candidate = env.receipts[0]
    if retry:
        monkeypatch.setattr(source, "MAX_COVERAGE_ARTIFACT_BYTES", 30)
    else:
        candidate = candidate.model_copy(update={
            "reservation": candidate.reservation.model_copy(update={"reservation_key": "new"})
        })
    preflight(env, candidate=candidate, reserved_sequence=10, _incremental_keys=set())
    env.lifecycle.assert_called_once()
    assert env.lifecycle.call_args.args[3] == candidate
    assert len(env.connection.aggregates) == 2
    if retry:
        assert env.lifecycle.call_args.kwargs == {
            "reserved_sequence": 1, "receipt_sequence": 3, "artifacts": None,
        }
    else:
        assert env.lifecycle.call_args.kwargs == {"reserved_sequence": 10, "artifacts": None}
    env.retention.assert_called_once()


def test_current_scope_and_candidate_are_both_checked_without_unrelated_history(env):
    preflight(
        env, candidate=env.receipts[0], reserved_sequence=1,
        _incremental_keys={env.receipts[1].reservation.key},
    )
    assert [call.args[3] for call in env.lifecycle.call_args_list] == env.receipts[:2]


def test_retry_lookup_by_reservation_key_rejects_changed_unit_even_outside_scope(env):
    candidate = env.receipts[0].model_copy(update={
        "reservation": env.receipts[0].reservation.model_copy(update={
            "key": env.receipts[1].reservation.key,
        })
    })
    with pytest.raises(ValueError, match="retry conflicts"):
        preflight(env, candidate=candidate, reserved_sequence=10, _incremental_keys=set())
    assert env.lifecycle.call_args.args[3] == env.receipts[0]


def test_candidate_plus_global_bytes_exceeds_bound_even_when_scope_is_empty(env):
    candidate = env.receipts[0].model_copy(update={
        "reservation": env.receipts[0].reservation.model_copy(update={"reservation_key": "new"})
    })
    env.connection.sizes["bytes"] = 31
    with pytest.raises(ValueError, match="cumulative read bound"):
        preflight(env, candidate=candidate, reserved_sequence=10, _incremental_keys=set())
    env.lifecycle.assert_called_once()


@pytest.mark.parametrize("damage", ["reservation", "size", "retention"])
def test_scoped_current_proof_still_refuses_tampering(env, damage):
    if damage == "reservation":
        env.connection.rows[1]["reservation"]["request_digest"] = "d" * 64
    elif damage == "size":
        env.connection.rows[1]["size_bytes"] += 1
    else:
        env.retention.side_effect = ValueError("retention expired")
    with pytest.raises(ValueError):
        preflight(env, _incremental_keys={env.receipts[1].reservation.key})
