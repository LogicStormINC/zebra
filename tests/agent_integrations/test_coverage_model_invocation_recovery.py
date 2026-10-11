"""Crash windows keep original charges/evidence and never renew transport authority."""

import gc
import json
from datetime import timedelta
from hashlib import sha256
from types import FunctionType
from weakref import WeakKeyDictionary, ref

import httpx
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_integrations.coverage_model_completion import encode_model_completion
from agent_integrations.coverage_model_policy import POLICY_KIND
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

from tests.agent_integrations import test_coverage_model_invocation as invocation_tests
from tests.agent_integrations.test_coverage_model_invocation import (
    compose,
    invoke,
    original,
)
from tests.agent_integrations.test_coverage_model_policy import proof

env = invocation_tests.env


def rewrite_payload(env, identifier, body):
    """Corrupt immutable evidence while retaining a self-consistent metadata hash."""
    env.payloads.bodies[identifier] = body
    env.payloads.rows[identifier] = env.payloads.rows[identifier].model_copy(
        update={
            "sha256": sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
    )


@pytest.mark.parametrize(
    "stage,settled,recoverable",
    [
        ("reserved", False, False),
        ("http", False, False),
        ("codec", False, False),
        ("before_publish", False, False),
        ("after_publish", False, True),
        ("before_ack", False, True),
        ("after_ack", True, True),
    ],
)
def test_crash_matrix_fresh_instances_never_second_http(
    env, monkeypatch, stage, settled, recoverable
):  # noqa: F811
    composed = compose(env)
    before = len(env.requests)
    with monkeypatch.context() as patch:
        if stage == "reserved":
            reserve = env.budget.reserve_model_call

            def crash(*args, **kwargs):
                reserve(*args, **kwargs)
                raise RuntimeError("crash after durable reservation")

            patch.setattr(env.budget, "reserve_model_call", crash)
        elif stage == "http":
            env.reply = httpx.ReadTimeout("unknown transport result")
        elif stage == "codec":

            def crash(*args, **kwargs):
                raise ValueError("full codec cannot preserve response")

            patch.setattr(
                "agent_integrations.coverage_model_invocation.encode_model_completion", crash
            )
        elif stage in {"before_publish", "after_publish"}:
            publish = env.payloads.store_payload_immutable

            def crash(payload, *, artifact_id):
                if payload.kind != MODEL_CHECKPOINT_KIND:
                    return publish(payload, artifact_id=artifact_id)
                if stage == "after_publish":
                    publish(payload, artifact_id=artifact_id)
                raise RuntimeError("publication interrupted")

            patch.setattr(env.payloads, "store_payload_immutable", crash)
        else:
            record = env.budget.record_model_usage

            def crash(*args, **kwargs):
                if stage == "after_ack":
                    record(*args, **kwargs)
                raise RuntimeError("usage acknowledgement interrupted")

            patch.setattr(env.budget, "record_model_usage", crash)
        with pytest.raises(CoverageRefusedError):
            invoke(env, composed)
    assert len(env.requests) - before == (0 if stage == "reserved" else 1)
    assert bool(env.budget.receipts) == settled
    key, reservation = next(iter(env.budget.calls.items()))
    state = env.budget.model_budget_state(env.binding)
    assert state.charged_tokens == (30 if settled else 1048576)
    assert state.unresolved == (0 if settled else 1)
    count = len(env.requests)
    fresh = compose(env)
    if recoverable:
        response = invoke(env, fresh)
        identifier, checkpoint = original(env)
        assert checkpoint.completion == encode_model_completion(response)
        assert env.budget.receipts[key].checkpoint_ref == f"artifact://{identifier}"
        assert env.budget.model_budget_state(env.binding).charged_tokens == 30
    else:
        with pytest.raises(CoverageRefusedError):
            invoke(env, fresh)
        assert env.budget.model_budget_state(env.binding).charged_tokens == 1048576
        assert not env.budget.receipts
    assert len(env.requests) == count
    assert env.budget.calls == {key: reservation}


@pytest.mark.parametrize("receipt", [False, True])
def test_missing_original_evidence_never_replay_or_retry(env, receipt):  # noqa: F811
    invoke(env)
    if not receipt:
        env.budget.receipts.clear()
    identifier, _ = original(env)
    del env.payloads.rows[identifier]
    del env.payloads.bodies[identifier]
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    assert len(env.requests) == 1 and len(env.budget.calls) == 1
    assert bool(env.budget.receipts) == receipt


@pytest.mark.parametrize(
    "mutation",
    [
        "bytes",
        "kind",
        "mime",
        "session",
        "retained",
        "pruned",
        "binding",
        "request",
        "v1",
        "full_codec",
        "receipt",
        "hash",
        "provider",
        "profile",
        "usage",
        "schema",
        "future_created",
    ],
)
@pytest.mark.parametrize("settled", [False, True])
def test_existing_corrupt_or_foreign_checkpoint_cannot_settle_or_replay(env, mutation, settled):  # noqa: F811
    invoke(env)
    identifier, checkpoint = original(env)
    if not settled:
        env.budget.receipts.clear()
    if mutation in {"kind", "mime", "session", "retained", "pruned", "future_created", "hash"}:
        changes = {
            "kind": {"kind": "public"},
            "mime": {"mime_type": "application/octet-stream"},
            "session": {"session_id": env.binding.task_id},
            "retained": {"retained_until": env.now},
            "pruned": {"lifecycle_status": "pruned", "pruned_at": env.now},
            "future_created": {"created_at": env.now + timedelta(seconds=1)},
            "hash": {"sha256": "f" * 64},
        }[mutation]
        env.payloads.rows[identifier] = env.payloads.rows[identifier].model_copy(update=changes)
    elif mutation == "receipt":
        if not settled:
            # A foreign receipt returned under the right reservation cannot acknowledge evidence.
            env.budget.receipts[checkpoint.reservation.reservation_key] = checkpoint_receipt(
                env, checkpoint
            ).model_copy(update={"checkpoint_digest": "f" * 64})
        else:
            key = checkpoint.reservation.reservation_key
            env.budget.receipts[key] = env.budget.receipts[key].model_copy(
                update={"checkpoint_digest": "f" * 64}
            )
    elif mutation == "bytes":
        env.payloads.bodies[identifier] = b"corrupt"
    else:
        data = json.loads(checkpoint.canonical_bytes)
        if mutation == "binding":
            data["binding"]["run_id"] = "foreign-run"
        elif mutation == "request":
            data["request"] += " "
        elif mutation == "v1":
            data["schema"] = "coverage-model-checkpoint/1"
            del data["request"]
        elif mutation == "schema":
            data["scope"] = "public"
        else:
            full = json.loads(data["completion"])
            if mutation == "full_codec":
                full["completion"]["assistant_message"]["metadata"] = ["not-a-map"]
            else:
                field, value = {
                    "provider": ("provider", "foreign"),
                    "profile": ("profile_id", "foreign"),
                    "usage": (
                        "usage",
                        {"input_tokens": True, "output_tokens": 20, "total_tokens": 21},
                    ),
                }[mutation]
                full["completion"]["call_metadata"][field] = value
            data["completion"] = json.dumps(
                full, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        body = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        rewrite_payload(env, identifier, body)
    before = dict(env.budget.receipts)
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    assert len(env.requests) == 1 and env.budget.receipts == before


def checkpoint_receipt(env, checkpoint):
    from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt

    return CoverageModelUsageReceipt(
        reservation=checkpoint.reservation,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        checkpoint_ref=f"artifact://{checkpoint.artifact_id}",
        checkpoint_digest=checkpoint.digest,
    )


def test_changed_exact_request_uses_original_unit_key_and_conflicts_unknown_reservation(env):  # noqa: F811
    env.reply = httpx.ReadTimeout("uncertain")
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    original_key = next(iter(env.budget.calls))
    # Same frozen rule/key/source, different exact valid serialization and hash.
    with pytest.raises(CoverageRefusedError) as refused:
        invoke(env, indent=2)
    assert "changed request" in str(refused.value.__cause__)
    assert list(env.budget.calls) == [original_key] and len(env.requests) == 1


@pytest.mark.parametrize(
    "changed",
    [
        "context",
        "output",
        "stored_version",
        "effective",
        "capacity_hash",
        "raw_bool",
        "effort_default",
        "effort_levels",
    ],
)
def test_resumed_policy_effective_fields_compare_original_without_overwrite(env, changed):  # noqa: F811
    invoke(env)
    identifier = next(key for key, row in env.payloads.rows.items() if row.kind == POLICY_KIND)
    if changed == "context":
        env.proof = proof(context_window=1048577)
    elif changed == "output":
        env.proof = proof(max_output_tokens=393217)
    elif changed == "effort_default":
        env.proof = proof(
            effort={"supported_levels": ["low", "high", "max"], "default_level": "low"}
        )
    elif changed == "effort_levels":
        env.proof = proof(effort={"supported_levels": ["low", "high"], "default_level": "high"})
    else:
        data = json.loads(env.payloads.bodies[identifier])
        if changed == "stored_version":
            data["effective"]["version"] = "coverage-deepseek-official/2"
        elif changed == "effective":
            data["effective"]["role"] = "executor"
        elif changed == "raw_bool":
            data["effective"]["retries"] = False
        else:
            data["capacity_hash"] = "f" * 64
        rewrite_payload(
            env,
            identifier,
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        )
    before = dict(env.payloads.bodies)
    with pytest.raises(CoverageRefusedError):
        compose(env)
    assert env.payloads.bodies == before and len(env.requests) == 1


def test_volatile_metadata_created_uses_persisted_original_exact_bytes(env):  # noqa: F811
    response = invoke(env)
    before = dict(env.payloads.bodies)
    env.proof = proof(created=1880000000)
    assert encode_model_completion(invoke(env)) == encode_model_completion(response)
    assert env.payloads.bodies == before and len(env.requests) == 1


@pytest.mark.parametrize("settled", [False, True])
def test_missing_policy_after_any_call_cannot_reestablish_proof(env, settled):  # noqa: F811
    if settled:
        invoke(env)
    else:
        env.reply = httpx.ReadTimeout("uncertain")
        with pytest.raises(CoverageRefusedError):
            invoke(env)
    identifier = next(key for key, row in env.payloads.rows.items() if row.kind == POLICY_KIND)
    del env.payloads.rows[identifier]
    del env.payloads.bodies[identifier]
    before = dict(env.payloads.bodies)
    with pytest.raises(CoverageRefusedError):
        compose(env)
    assert env.payloads.bodies == before and len(env.requests) == 1


@pytest.mark.parametrize("failure", ["missing_usage", "foreign_model", "semantic", "finish"])
def test_response_failures_remain_charged_semantics_only_after_usage(env, failure):  # noqa: F811
    if failure == "missing_usage":
        del env.reply["usage"]
    elif failure == "foreign_model":
        env.reply["model"] = "deepseek-chat"
    elif failure == "semantic":
        env.reply["choices"][0]["message"]["content"] = "not valid semantic JSON"
    else:
        env.reply["choices"][0]["finish_reason"] = "length"
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    before = dict(env.budget.receipts)
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    assert len(env.requests) == 1 and env.budget.receipts == before
    state = env.budget.model_budget_state(env.binding)
    # The approved provider parser rejects truncated output before a completion exists.
    accounted = failure == "semantic"
    assert state.charged_tokens == (30 if accounted else 1048576)
    assert state.unresolved == (0 if accounted else 1)


@pytest.mark.parametrize("boundary", ["reserve", "network", "publish", "ack", "return"])
@pytest.mark.parametrize("failure", ["STOP", "deadline", "manifest", "policy"])
def test_fresh_authority_deadline_and_source_lifecycle_every_boundary(
    env, monkeypatch, boundary, failure
):  # noqa: F811
    composition = compose(env)

    def revoke():
        if failure == "STOP":
            env.authority_error = Reason.CANCELLED
        elif failure == "deadline":
            env.now = env.policy.deadline
        else:
            identifier = composition.manifest_id if failure == "manifest" else composition.policy_id
            env.payloads.rows[identifier] = env.payloads.rows[identifier].model_copy(
                update={"retained_until": env.now}
            )

    if boundary == "reserve":
        factory = env.factory

        def changed():
            result = factory()
            revoke()
            return result

        composition.gateway_factory = changed
    elif boundary == "network":
        reserve = env.budget.reserve_model_call

        def changed(*args, **kwargs):
            result = reserve(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(env.budget, "reserve_model_call", changed)
    elif boundary == "publish":
        send = OpenAICompatibleModelGateway.complete_prepared

        def changed(*args, **kwargs):
            result = send(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(OpenAICompatibleModelGateway, "complete_prepared", changed)
    elif boundary == "ack":
        publish = env.payloads.store_payload_immutable

        def changed(payload, *, artifact_id):
            result = publish(payload, artifact_id=artifact_id)
            if payload.kind == MODEL_CHECKPOINT_KIND:
                revoke()
            return result

        monkeypatch.setattr(env.payloads, "store_payload_immutable", changed)
    else:
        record = env.budget.record_model_usage

        def changed(*args, **kwargs):
            result = record(*args, **kwargs)
            revoke()
            return result

        monkeypatch.setattr(env.budget, "record_model_usage", changed)
    with pytest.raises(CoverageRefusedError):
        invoke(env, composition)
    assert len(env.requests) == (0 if boundary in {"reserve", "network"} else 1)
    assert bool(env.budget.receipts) == (boundary == "return")


def test_existing_finalized_checkpoint_even_when_reserve_says_invoke_never_sends(env):
    response = invoke(env)
    env.budget.calls.clear()
    env.budget.receipts.clear()
    # Exercise the defensive invoke=True branch; real Event stores never erase history.
    restored = invoke(env)
    assert encode_model_completion(response) == encode_model_completion(restored)
    assert len(env.requests) == 1 and len(env.budget.receipts) == 1


def test_checkpoint_pruned_between_ack_and_observation_refuses_return(env, monkeypatch):
    composition = compose(env)
    record = env.budget.record_model_usage

    def prune_after_ack(*args, **kwargs):
        result = record(*args, **kwargs)
        identifier, _ = original(env)
        env.payloads.rows[identifier] = env.payloads.rows[identifier].model_copy(
            update={"retained_until": env.now}
        )
        return result

    monkeypatch.setattr(env.budget, "record_model_usage", prune_after_ack)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        invoke(env, composition)
    assert len(env.requests) == 1 and len(env.budget.receipts) == 1


def test_earliest_policy_retention_expires_during_later_read(env, monkeypatch):
    invoke(env)
    identifier, _ = original(env)
    policy_id = next(key for key, row in env.payloads.rows.items() if row.kind == POLICY_KIND)
    expires = env.now + timedelta(seconds=2)
    env.payloads.rows[policy_id] = env.payloads.rows[policy_id].model_copy(
        update={"retained_until": expires}
    )
    read = env.payloads.read_payload_bytes_bounded

    def expire_during_checkpoint_read(artifact_id, *, max_bytes):
        result = read(artifact_id, max_bytes=max_bytes)
        if artifact_id == identifier:
            env.now = expires
        return result

    monkeypatch.setattr(env.payloads, "read_payload_bytes_bounded", expire_during_checkpoint_read)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        invoke(env)
    assert len(env.requests) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "callback",
        "defaults",
        "foreign_ref",
        "ref_callback",
        "ref_subclass",
        "globals",
        "pending",
        "pending_subclass",
        "iterating",
        "iterating_subclass",
        "dirty",
        "extra",
    ],
)
def test_registry_callback_and_raw_state_refused_before_prepare(env, mutation):
    response = invoke(env)
    composition = compose(env)
    factory = env.factory
    attempted = []

    def changed():
        gateway = factory()
        registry = gateway._prepared_requests._issued
        native = registry._remove

        def hidden_send(*args):
            attempted.append(True)
            gateway._post_chat_completion(b"{}", endpoint=env.proof.chat_url)
            return registry

        if mutation == "callback":
            hidden_send.__name__ = native.__name__
            hidden_send.__qualname__ = native.__qualname__
            registry._remove = hidden_send
        elif mutation == "defaults":
            native.__defaults__ = (hidden_send,)
        elif mutation == "foreign_ref":
            native.__defaults__ = (ref(WeakKeyDictionary()),)
        elif mutation == "ref_callback":
            native.__defaults__ = (ref(registry, hidden_send),)
        elif mutation == "ref_subclass":

            class ForeignRef(ref):
                def __call__(self):
                    return hidden_send()

            native.__defaults__ = (ForeignRef(registry),)
        elif mutation == "globals":
            registry._remove = FunctionType(native.__code__, {}, argdefs=native.__defaults__)
        elif mutation == "pending":
            registry._pending_removals = [object()]
        elif mutation == "pending_subclass":
            registry._pending_removals = type("ForeignList", (list,), {})()
        elif mutation == "iterating":
            registry._iterating = {object()}
        elif mutation == "iterating_subclass":
            registry._iterating = type("ForeignSet", (set,), {})()
        elif mutation == "dirty":
            registry._dirty_len = 1
        else:
            registry.extra = True
        return gateway

    composition.gateway_factory = changed
    fences = len(env.budget.fences)
    with pytest.raises(CoverageRefusedError):
        invoke(env, composition)
    gc.collect()
    assert not attempted and len(env.requests) == 1
    assert len(env.budget.fences) == fences  # No new reservation on refused replay.
    assert len(env.budget.calls) == len(env.budget.receipts) == 1
    assert encode_model_completion(response) == original(env)[1].completion


@pytest.mark.parametrize("settled", [False, True])
@pytest.mark.parametrize("boundary", ["reserve", "cleanup"])
def test_native_callback_defaults_mutated_after_prepare_never_gc_send(
    env, monkeypatch, settled, boundary
):
    if settled:
        invoke(env)
    composition = compose(env)
    factory = env.factory
    registries, attempted = [], []

    def capture():
        gateway = factory()
        registries.append(gateway._prepared_requests._issued)
        return gateway

    def mutate():
        registry = registries[-1]

        def hidden_send():
            attempted.append(True)
            gateway = factory()
            gateway._post_chat_completion(b"{}", endpoint=env.proof.chat_url)
            return registry

        registry._remove.__defaults__ = (hidden_send,)

    composition.gateway_factory = capture
    if boundary == "reserve":
        reserve = env.budget.reserve_model_call

        def changed(*args, **kwargs):
            result = reserve(*args, **kwargs)
            mutate()
            return result

        monkeypatch.setattr(env.budget, "reserve_model_call", changed)
    else:
        from agent_integrations import coverage_model_invocation

        derive = coverage_model_invocation.derive_semantic_observation

        def changed(*args, **kwargs):
            result = derive(*args, **kwargs)
            mutate()
            return result

        monkeypatch.setattr(coverage_model_invocation, "derive_semantic_observation", changed)
    with pytest.raises(CoverageRefusedError):
        invoke(env, composition)
    gc.collect()
    assert not attempted and not registries[-1].data
    assert len(env.requests) == (1 if settled or boundary == "cleanup" else 0)
    assert len(env.budget.calls) == 1
    assert bool(env.budget.receipts) == (settled or boundary == "cleanup")
