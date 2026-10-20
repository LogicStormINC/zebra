"""Pure orchestration regressions; native authority/object proof belongs to main's gates."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from agent_core.domain.coverage_legacy_source import LEGACY_COVERAGE_SOURCE
from agent_core.domain.events import EventType
from agent_storage.postgres import coverage_model_verification as verification
from zebra_agent_worker import coverage_recovery as recovery
from zebra_agent_worker import coverage_recovery_authority as authority

from tests.agent_storage.test_coverage_model_verification import phase


def recovery_phase(monkeypatch, *, state, accepted=False, native_read=None):
    _, binding, counts = phase(monkeypatch)
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=5)
    policy = SimpleNamespace(
        model_profile=recovery.REVIEWER_PROFILE,
        task_binding_digest="binding",
        started_at=now - timedelta(seconds=5),
        deadline=expiry,
    )
    binding.contract.source_definition = LEGACY_COVERAGE_SOURCE
    binding.task_id = "task"
    binding.snapshot.expires_at = expiry
    binding.snapshot.source_resource_ref = "history"
    binding.snapshot.snapshot_id = "snapshot"
    binding.snapshot.model_dump = lambda **_: {}
    host = SimpleNamespace(expires_at=expiry, namespace_id="host-namespace")

    class Pinned:
        binding_digest = "binding"
        binding_revision = 1
        host_capability = SimpleNamespace(host_context=host, manifest_digest="manifest")

        @classmethod
        def model_validate_json(cls, *_, **__):
            return pinned

        @classmethod
        def model_validate(cls, value, **_):
            return value

    pinned = Pinned()
    rows = [
        {
            "event_id": "manifest",
            "event_type": EventType.COVERAGE_MANIFEST_COMMITTED.value,
            "sequence": 0,
            "payload": {
                "namespace": binding.namespace,
                "run_id": binding.run_id,
                "task_binding_digest": "binding",
                "task_binding_revision": 1,
            },
        }
    ]
    if accepted:
        rows.append(
            {
                "event_id": "batch",
                "event_type": EventType.COVERAGE_BATCH_ACCEPTED.value,
                "sequence": 1,
                "payload": {},
            }
        )

    class Connection:
        def execute(self, sql, params):
            if native_read is not None:
                result = native_read(sql, params)
                if result is not None:
                    return result
            if "octet_length(to_jsonb(e)" in sql:
                counts["history_queries"] = counts.get("history_queries", 0) + 1
                row, values = None, [
                    dict(r, history_count=len(rows), history_bytes=1) for r in rows
                ]
            elif "FROM agent_tasks" in sql:
                row, values = (
                    {
                        "active_segment_id": binding.session_id,
                        "snapshot_json": {},
                        "binding_digest": "binding",
                        "namespace_id": host.namespace_id,
                    },
                    [],
                )
            elif "FROM effect_outbox" in sql:
                row, values = None, []
            elif "octet_length(to_jsonb(u)" in sql:
                counts["unit_queries"] = counts.get("unit_queries", 0) + 1
                row, values = None, [{"unit_count": 0, "unit_bytes": 0, "unit_digest": None}]
            else:
                assert "FROM coverage_units" in sql
                row, values = None, []
            return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: values)

    def replay(*_, **kwargs):
        counts["ledger"] += 1
        assert kwargs["source_keys"] == set()
        kwargs["retention_deadlines"].append(expiry - timedelta(seconds=1))
        return state, {}

    def event(row):
        assert "history_count" not in row and "history_bytes" not in row
        return SimpleNamespace(
            event_type=EventType(row["event_type"]),
            sequence=row["sequence"],
            payload=row["payload"],
            model_dump=lambda **_: row,
        )

    gateway = SimpleNamespace(
        endpoint="endpoint",
        workload_identity="identity",
        shared_secret="secret",
        invoke=lambda *_: None,
    )
    descriptor = object()
    monkeypatch.setattr(verification, "task_policy", lambda *_: policy)
    monkeypatch.setattr(verification, "replay_model", replay)
    monkeypatch.setattr(recovery, "task_policy", lambda *_: policy)
    monkeypatch.setattr(recovery, "binding_from_event", lambda *_: binding)
    monkeypatch.setattr(
        recovery,
        "lock_run",
        lambda *_: (
            {"cancelled": False, "source_watermark": 0},
            len(rows) - 1,
        ),
    )
    monkeypatch.setattr(recovery, "assert_projection", lambda *_: None)
    monkeypatch.setattr(recovery, "TaskBindingSnapshot", Pinned)
    # Authority preparation moved to its own module. This pure SQL/orchestration
    # fixture has no native lineage database; retain the independent binding/time
    # fallback rather than patch a removed symbol or bypass current() entirely.
    monkeypatch.setattr(authority, "TaskBindingSnapshot", Pinned)
    monkeypatch.setattr(authority, "effect_input", lambda value: value)
    monkeypatch.setattr(authority.PostgresCoverageAuthority, "prepare", lambda *_: None)
    monkeypatch.setattr(
        recovery,
        "semantic_check",
        lambda *_: SimpleNamespace(
            contract_check="check",
        ),
    )
    monkeypatch.setattr(recovery, "SessionEvent", SimpleNamespace(model_validate=event))
    monkeypatch.setattr(recovery, "resolve_pinned_gateway", lambda *_: gateway)
    monkeypatch.setattr(recovery, "frozen_or_discovered_manifest", lambda *_: None)
    monkeypatch.setattr(recovery.httpx, "Client", lambda **_: nullcontext(SimpleNamespace()))
    monkeypatch.setattr(recovery, "HttpHostToolTransport", lambda **_: None)
    monkeypatch.setattr(
        recovery,
        "HostCoverageSnapshotSource",
        lambda **_: SimpleNamespace(
            host=SimpleNamespace(budget=lambda *_: None),
            _get_descriptor=lambda *_: descriptor,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "Descriptor",
        SimpleNamespace(
            model_validate=lambda *_: descriptor,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "model_provider_settings",
        lambda *_: SimpleNamespace(
            api_key_env="COVERAGE_PURE_TEST_NO_CREDENTIAL",
        ),
    )
    monkeypatch.setattr(recovery, "load_official_model_policy", lambda **_: None)
    monkeypatch.setattr(recovery, "PostgresCoverageArtifactPublisher", lambda *_, **__: None)
    monkeypatch.setattr(recovery, "CloudCoverageArtifacts", lambda **_: object())
    monkeypatch.setattr(recovery, "pin_evidence", lambda *_: 1)
    monkeypatch.setattr(recovery, "read_manifest", lambda *_: ())
    monkeypatch.setattr(recovery, "expected_units", lambda *_, **__: ())
    monkeypatch.setattr(
        recovery,
        "replay_request",
        lambda *_: SimpleNamespace(
            results=(),
            result_artifact_ref="batch",
            result_artifact_digest="digest",
        ),
    )
    monkeypatch.setattr(recovery, "check_checkpoint_retention", lambda *_: now)
    runtime = SimpleNamespace(
        deployment_namespace="deployment",
        dsn="unused",
        objects=None,
        metadata=SimpleNamespace(
            _database=SimpleNamespace(
                _dsn="unused",
                deployment_namespace="deployment",
            )
        ),
    )
    service = SimpleNamespace(
        _task_binding_loader=lambda *_: pinned,
        _egress_registry=None,
        _settings=SimpleNamespace(host_tool_shared_secret="unused"),
        _frozen_manifest_loader=None,
    )
    pending = {
        "session_id": binding.session_id,
        "created_at": now,
        "accepted_event_id": "command",
    }
    receipt = {
        "control_plane_epoch": "00000000-0000-0000-0000-000000000001",
        "fencing_token": 1,
        "owner_instance_id": "worker",
        "execution_floor_sequence": len(rows),
        "wake_generation": 1,
    }
    return (
        lambda: recovery.verify_cloud_coverage_recovery(
            runtime,
            service,
            Connection(),
            "deployment",
            pending,
            receipt,
        ),
        counts,
        expiry,
    )


@pytest.mark.parametrize("initialized", [False, True])
def test_recovery_replays_once_per_invocation_and_preserves_retention(monkeypatch, initialized):
    run, counts, expiry = recovery_phase(
        monkeypatch,
        state=SimpleNamespace(unresolved=0) if initialized else None,
        accepted=initialized,
    )
    for invocation in (1, 2):
        proof = run()
        assert counts["ledger"] == invocation
        assert counts["history_queries"] == counts["unit_queries"] == invocation
        assert proof["valid_until"] == (expiry - timedelta(seconds=1)).isoformat()


@pytest.mark.parametrize("unresolved", [False, True])
def test_recovery_refuses_uninitialized_accepted_or_unresolved_attempt(monkeypatch, unresolved):
    run, counts, _ = recovery_phase(
        monkeypatch,
        state=SimpleNamespace(unresolved=1) if unresolved else None,
        accepted=not unresolved,
    )
    message = "requires reconciliation" if unresolved else "no initialized budget"
    with pytest.raises(ValueError, match=message):
        run()
    assert counts["ledger"] == 1 and counts["request"] == 0


def test_recovery_preserves_original_replay_failure(monkeypatch):
    run, counts, _ = recovery_phase(monkeypatch, state=SimpleNamespace(unresolved=0))
    failure = ValueError("original checkpoint unavailable")

    def failed_replay(*_, **__):
        counts["ledger"] += 1
        raise failure

    monkeypatch.setattr(verification, "replay_model", failed_replay)
    with pytest.raises(ValueError) as caught:
        run()
    assert caught.value is failure
    assert counts["ledger"] == 1 and counts["request"] == 0
