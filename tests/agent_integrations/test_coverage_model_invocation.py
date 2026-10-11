"""Existing fake Ports plus actual prepared MockTransport; no network-origin proof."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.artifact_payloads import (
    ArtifactPayloadInspection,
    ArtifactPayloadLifecycleStatus,
    ArtifactPayloadStatus,
    StoredArtifactPayload,
)
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelReservationResult,
)
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoveragePart, CoverageRecord
from agent_core.domain.coverage_validation import CoverageUnitKey, manifest_digest
from agent_core.domain.identifiers import ArtifactId, new_message_id
from agent_core.domain.leases import LeaseFence
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelInvocationPolicy, ModelRole, ModelToolChoice
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_model_completion import encode_model_completion
from agent_integrations.coverage_model_invocation import CoverageModelInvocation
from agent_integrations.coverage_model_policy import POLICY_KIND, REVIEWER_PROFILE
from agent_integrations.coverage_model_request import PreparedChatRequests
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

from tests.agent_core.test_coverage_model_checkpoint import checkpoint as base_checkpoint
from tests.agent_integrations.test_coverage_model_policy import proof


class Payloads:
    """Only payload metadata/bytes exist: no public Artifact projection capability."""

    def __init__(self):
        self.rows, self.bodies, self.writes = {}, {}, []

    def store_payload_immutable(self, payload, *, artifact_id):
        if artifact_id in self.rows:
            assert self.bodies[artifact_id] == payload.payload
            return self.rows[artifact_id]
        stored = StoredArtifactPayload(
            artifact_id=artifact_id,
            session_id=payload.session_id,
            kind=payload.kind,
            mime_type=payload.mime_type,
            uri=f"artifact://{artifact_id}",
            sha256=sha256(payload.payload).hexdigest(),
            size_bytes=len(payload.payload),
            lifecycle_status=ArtifactPayloadLifecycleStatus.ACTIVE,
            created_at=payload.created_at,
            retained_until=payload.retained_until,
        )
        self.rows[artifact_id], self.bodies[artifact_id] = stored, payload.payload
        self.writes.append(payload)
        return stored

    def get_payload(self, artifact_id):
        return self.rows.get(artifact_id)

    def inspect_payload(self, artifact_id):
        stored = self.rows.get(artifact_id)
        if stored is None:
            return None
        return ArtifactPayloadInspection(
            artifact_id=artifact_id,
            status=ArtifactPayloadStatus.AVAILABLE,
            payload=stored,
        )

    def read_payload_bytes_bounded(self, artifact_id, *, max_bytes):
        body = self.bodies[artifact_id]
        if len(body) > max_bytes:
            raise ValueError("bounded read overflow")
        return body


class Budget:
    def __init__(self, policy):
        self.policy, self.calls, self.receipts, self.fences = policy, {}, {}, []

    def initialize_model_budget(self, binding, *, fence):
        self.fences.append(fence)
        return self.policy

    def model_budget_state(self, binding):
        charged = sum(
            self.receipts[key].total_tokens if key in self.receipts else row.token_bound
            for key, row in self.calls.items()
        )
        return CoverageModelBudgetState(
            policy=self.policy,
            calls=len(self.calls),
            charged_tokens=charged,
            unresolved=len(self.calls) - len(self.receipts),
        )

    def reserve_model_call(self, binding, reservation, *, fence):
        self.fences.append(fence)
        previous = self.calls.get(reservation.reservation_key)
        if previous is not None:
            if previous != reservation:
                raise ValueError("changed request under original reservation key")
            return CoverageModelReservationResult(
                reservation=previous,
                invoke=False,
                event_watermark=2,
                receipt=self.receipts.get(reservation.reservation_key),
            )
        state = self.model_budget_state(binding)
        if (
            state.calls >= self.policy.max_calls
            or state.charged_tokens + reservation.token_bound > self.policy.max_tokens
        ):
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        self.calls[reservation.reservation_key] = reservation
        return CoverageModelReservationResult(
            reservation=reservation,
            invoke=True,
            event_watermark=2,
        )

    def record_model_usage(self, binding, receipt, *, fence):
        self.fences.append(fence)
        assert self.calls[receipt.reservation.reservation_key] == receipt.reservation
        self.receipts[receipt.reservation.reservation_key] = receipt
        return 3


def environment():
    base = base_checkpoint().binding
    definition = semantic_check(REVIEWER_PROFILE)
    source = 'source🙂 停产。\n"quoted"'
    part = CoveragePart(
        id="part-1",
        digest=sha256(source.encode()).hexdigest(),
        byte_length=len(source.encode()),
    )
    record = CoverageRecord(ordinal=0, record_id="record-1", content_digest="a" * 64, parts=(part,))
    manifest = coverage_manifest_bytes((record,))
    contract = base.contract.model_copy(update={"checks": (definition.contract_check,)})
    identifier = ArtifactId(uuid4())
    snapshot = base.snapshot.model_copy(
        update={
            "contract_digest": contract.digest,
            "manifest_digest": manifest_digest(contract, (record,)),
            "record_count": 1,
            "source_resource_ref": "history-1",
            "manifest_artifact_ref": f"artifact://{identifier}",
        }
    )
    binding = CoverageRunBinding(
        **{
            **base.model_dump(),
            "contract": contract,
            "snapshot": snapshot,
            "manifest_artifact_digest": sha256(manifest).hexdigest(),
        }
    )
    key = CoverageUnitKey(
        record_id=record.record_id,
        content_digest=record.content_digest,
        kind="part",
        part_id=part.id,
        part_digest=part.digest,
        check_id=definition.id,
        check_version=definition.version,
        definition_digest=definition.contract_check.definition_digest,
    )
    policy = CoverageModelPolicy(
        admission_event_digest="b" * 64,
        admission_digest="c" * 64,
        task_binding_digest="d" * 64,
        model_profile=REVIEWER_PROFILE,
        max_calls=10,
        max_tokens=1048576 * 10,
        max_runtime_seconds=3600,
        started_at=snapshot.as_of,
        deadline=snapshot.as_of + timedelta(seconds=3600),
    )
    env = SimpleNamespace(
        binding=binding,
        definition=definition,
        key=key,
        record=record,
        source=source,
        policy=policy,
        proof=proof(),
        payloads=Payloads(),
        budget=Budget(policy),
        now=snapshot.as_of + timedelta(seconds=1),
        authority_error=None,
        requests=[],
        clients=[],
        gates=[],
        fence_token=0,
    )
    env.artifacts = CoverageArtifacts(env.payloads, binding.session_id, nullcontext())
    env.artifacts.publish(
        identifier,
        "coverage_manifest",
        manifest,
        33554432,
        lambda: env.now,
        snapshot.expires_at,
    )
    env.reply = {
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "reasoning_content": "私有完整推理🙂",
                    "content": json.dumps(
                        {
                            "key": key.model_dump(mode="json"),
                            "outcome": "clear",
                            "categories": [],
                            "quotes": [],
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }

    def handle(request):
        env.requests.append(request)
        if isinstance(env.reply, Exception):
            raise env.reply
        return httpx.Response(200, json=env.reply)

    def factory():
        client = httpx.Client(
            transport=httpx.MockTransport(handle),
            trust_env=False,
            follow_redirects=False,
        )
        env.clients.append(client)
        gateway = OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://api.deepseek.com",
            api_key="test-only",
            model_name="deepseek-v4-pro",
            max_retries=0,
            client=client,
        )
        env.gates.append(gateway)
        return gateway

    def authority():
        if env.authority_error:
            raise CoverageRefusedError(env.authority_error)

    def fence():
        env.fence_token += 1
        return LeaseFence(
            control_plane_epoch=binding.session_id,
            fencing_token=env.fence_token,
            owner_instance_id="fresh-worker",
        )

    env.factory, env.authority, env.fence = factory, authority, fence
    return env


@pytest.fixture
def env():
    value = environment()
    yield value
    for client in value.clients:
        client.close()


def compose(env, **changes):
    return CoverageModelInvocation(
        **{
            "binding": env.binding,
            "artifacts": env.artifacts,
            "budget_store": env.budget,
            "original_policy": env.policy,
            "fresh_fence": env.fence,
            "check_authority": env.authority,
            "gateway_factory": env.factory,
            "trusted_proof": env.proof,
            "allow_mock_transport": True,
            "now": lambda: env.now,
            **changes,
        }
    )


def messages(env, *, indent=None):
    return [
        SessionMessage(message_id=new_message_id(), created_at=env.now, role=role, content=text)
        for role, text in (
            (MessageRole.SYSTEM, env.definition.instructions),
            (
                MessageRole.USER,
                json.dumps(
                    {
                        "key": env.key.model_dump(mode="json"),
                        "bodies": {env.key.part_id: env.source},
                    },
                    ensure_ascii=False,
                    indent=indent,
                ),
            ),
        )
    ]


def invoke(env, composition=None, *, indent=None):
    return (composition or compose(env))(
        messages(env, indent=indent),
        ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            profile_id=REVIEWER_PROFILE,
            tool_choice=ModelToolChoice.NONE,
            max_output_tokens=8192,
        ),
    )


def original(env):
    identifier = next(
        key for key, row in env.payloads.rows.items() if row.kind == MODEL_CHECKPOINT_KIND
    )
    return identifier, decode_model_checkpoint(env.payloads.bodies[identifier])


def test_one_http_full_bound_exact_private_checkpoint_and_original_replay(env):
    first = invoke(env)
    second = invoke(env)
    assert len(env.requests) == 1 and len(env.budget.calls) == 1
    assert encode_model_completion(first) == encode_model_completion(second)
    identifier, checkpoint = original(env)
    assert checkpoint.binding == env.binding
    assert checkpoint.request == env.requests[0].content
    assert checkpoint.reservation.token_bound == 1048576
    assert checkpoint.completion == encode_model_completion(first)
    assert second.assistant_message.provider_reasoning_content == "私有完整推理🙂"
    receipt = next(iter(env.budget.receipts.values()))
    checkpoint.validate_receipt(receipt)
    assert receipt.checkpoint_digest == sha256(env.payloads.bodies[identifier]).hexdigest()
    state = env.budget.model_budget_state(env.binding)
    assert state.charged_tokens == 30 and state.unresolved == 0 and state.calls == 1
    kinds = [write.kind for write in env.payloads.writes]
    assert kinds == ["coverage_manifest", POLICY_KIND, MODEL_CHECKPOINT_KIND]
    assert all(write.mime_type == "application/json" for write in env.payloads.writes[1:])
    assert not hasattr(env.payloads, "publish_artifact")  # No public projection operation.
    assert len({fence.fencing_token for fence in env.budget.fences}) == len(env.budget.fences)


def test_strict_callback_is_exclusive_and_semantic_adapter_never_ordinary_complete(
    env, monkeypatch
):
    def fail(*args, **kwargs):
        pytest.fail("strict callback must never call ordinary complete")

    monkeypatch.setattr(OpenAICompatibleModelGateway, "complete", fail)
    model = SemanticCoverageModel(
        model_profile=REVIEWER_PROFILE,
        check_authority=env.authority,
        invoke_or_replay=compose(env),
    )
    assert model(env.definition, env.key, {env.key.part_id: env.source}).outcome == "clear"
    assert model(env.definition, env.key, {env.key.part_id: env.source}).outcome == "clear"
    assert len(env.requests) == 1
    with pytest.raises(ValueError):
        SemanticCoverageModel(model_profile=REVIEWER_PROFILE, check_authority=env.authority)
    for extra in (
        {"gateway": env.factory()},
        {"reserve_call": lambda: None},
        {"record_response": lambda response: None},
    ):
        with pytest.raises(ValueError):
            SemanticCoverageModel(
                model_profile=REVIEWER_PROFILE,
                check_authority=env.authority,
                invoke_or_replay=compose(env),
                **extra,
            )


@pytest.mark.parametrize(
    "failure",
    [
        "instructions",
        "source",
        "unit",
        "profile",
        "output",
        "proxy",
        "provider",
        "model",
        "retry",
        "capacity",
        "budget",
        "policy",
        "raw_policy",
        "authority",
    ],
)
def test_pretransport_refusals_never_reserve_or_send(env, failure):
    options = {}
    if failure == "capacity":
        env.proof = proof(context_window=env.policy.max_tokens + 1)
    elif failure == "budget":
        env.policy = env.policy.model_copy(update={"max_tokens": 1048575})
        env.budget.policy = env.policy
    elif failure == "policy":
        env.policy = env.policy.model_copy(update={"admission_digest": "e" * 64})
    elif failure == "raw_policy":
        env.policy = env.policy.model_copy(update={"max_tokens": True})
    elif failure == "authority":
        env.authority_error = Reason.CANCELLED
    elif failure in {"proxy", "provider", "model", "retry"}:
        factory = env.factory
        field, value = {
            "proxy": ("_base_url", "https://proxy.invalid"),
            "provider": ("_provider_name", "proxy"),
            "model": ("_model_name", "alias"),
            "retry": ("_max_retries", 1),
        }[failure]

        def bad_factory():
            gateway = factory()
            setattr(gateway, field, value)
            return gateway

        options["gateway_factory"] = bad_factory
    with pytest.raises(CoverageRefusedError):
        composed = compose(env, **options)
        msg = messages(env)
        policy = ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            profile_id=REVIEWER_PROFILE,
            tool_choice=ModelToolChoice.NONE,
            max_output_tokens=8192,
        )
        if failure == "instructions":
            msg[0] = msg[0].model_copy(update={"content": "different rule"})
        elif failure in {"source", "unit"}:
            payload = json.loads(msg[1].content)
            if failure == "source":
                payload["bodies"][env.key.part_id] = "foreign source"
            else:
                payload["key"]["record_id"] = "foreign record"
            msg[1] = msg[1].model_copy(update={"content": json.dumps(payload)})
        elif failure == "profile":
            policy = replace(policy, profile_id="deepseek-v4-pro-planner-v1")
        elif failure == "output":
            policy = replace(policy, max_output_tokens=8193)
        composed(msg, policy)
    assert not env.budget.calls and not env.requests


def test_legacy_mime_default_and_json_opt_in_use_same_publication_loop(env):
    identifier = ArtifactId(uuid4())
    uri = env.artifacts.publish(
        identifier, "legacy", b"bytes", 5, lambda: env.now, env.binding.snapshot.expires_at
    )
    assert uri == f"artifact://{identifier}"
    assert env.artifacts.load(identifier, "legacy", 5, env.now)[1] == b"bytes"
    assert env.payloads.rows[identifier].mime_type == "application/octet-stream"
    with pytest.raises(CoverageRefusedError):
        env.artifacts.load(identifier, "legacy", 5, env.now, mime_type="application/json")


@pytest.mark.parametrize("client_kind", ["mock", "unverified_tls", "verified_tls"])
def test_production_rejects_injected_clients_before_reservation(env, client_kind):
    def factory():
        if client_kind == "mock":
            return env.factory()
        client = httpx.Client(verify=client_kind != "unverified_tls", trust_env=False)
        env.clients.append(client)
        return OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://api.deepseek.com",
            api_key="test-only",
            model_name="deepseek-v4-pro",
            max_retries=0,
            client=client,
        )

    with pytest.raises(CoverageRefusedError):
        invoke(env, compose(env, gateway_factory=factory, allow_mock_transport=False))
    assert not env.budget.calls and not env.requests


def test_native_owned_client_is_admitted_without_network_in_this_check(env, monkeypatch):
    def native():
        gateway = env.factory()
        gateway._client = None
        return gateway

    reserve = env.budget.reserve_model_call

    def stop_after_reservation(*args, **kwargs):
        result = reserve(*args, **kwargs)
        env.authority_error = Reason.CANCELLED
        return result

    monkeypatch.setattr(env.budget, "reserve_model_call", stop_after_reservation)
    with pytest.raises(CoverageRefusedError, match="cancelled"):
        invoke(env, compose(env, gateway_factory=native, allow_mock_transport=False))
    assert len(env.budget.calls) == 1 and not env.requests


def test_builtin_gateway_instance_method_override_refuses_before_reservation(env):
    def overridden():
        gateway = env.factory()
        gateway.complete_prepared = lambda prepared: pytest.fail("foreign transport")
        return gateway

    with pytest.raises(CoverageRefusedError):
        invoke(env, compose(env, gateway_factory=overridden))
    assert not env.budget.calls and not env.requests


@pytest.mark.parametrize("mutation", ["duplicate", "bool", "extra", "nonfinite", "extra_message"])
def test_exact_semantic_request_raw_fields_checked_before_reservation(env, mutation):
    composition = compose(env)
    msg = messages(env)
    payload = json.loads(msg[1].content)
    if mutation == "duplicate":
        text = msg[1].content.replace('"bodies":', '"bodies":{},"bodies":')
    elif mutation == "extra_message":
        msg.append(msg[1])
        text = msg[1].content
    else:
        if mutation == "bool":
            payload["key"]["check_version"] = True
        elif mutation == "extra":
            payload["new_field"] = "untrusted"
        else:
            payload["number"] = float("nan")
        text = json.dumps(payload)
    msg[1] = msg[1].model_copy(update={"content": text})
    with pytest.raises(CoverageRefusedError):
        composition(
            msg,
            ModelInvocationPolicy(
                role=ModelRole.REVIEWER,
                profile_id=REVIEWER_PROFILE,
                tool_choice=ModelToolChoice.NONE,
                max_output_tokens=8192,
            ),
        )
    assert not env.budget.calls and not env.requests


def test_membership_is_verified_once_each_constructor(env, monkeypatch):
    verify = CoverageRunBinding.verify_manifest
    calls = []

    def counted(binding, payload):
        calls.append(payload)
        return verify(binding, payload)

    monkeypatch.setattr(CoverageRunBinding, "verify_manifest", counted)
    composition = compose(env)
    assert len(calls) == 1
    invoke(env, composition)
    invoke(env, composition)
    assert len(calls) == 1 and len(env.requests) == 1
    compose(env)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "send_subclass",
        "send_instance",
        "prepare_subclass",
        "replacement",
        "prepare_instance",
        "router_instance",
        "registry_instance",
        "registry_dict",
        "router_dict",
    ],
)
def test_modified_internal_delegates_refuse_before_prepare_and_reservation(env, mutation):
    attempted = []

    class DoubleSend(PreparedChatRequests):
        def send(self, gateway, request):
            attempted.append("extra send")
            gateway._post_chat_completion(request.body, endpoint=request.endpoint)
            return super().send(gateway, request)

    class EarlyPrepare(PreparedChatRequests):
        def prepare(self, gateway, *args, **kwargs):
            attempted.append("early prepare")
            gateway._post_chat_completion(
                b"{}", endpoint="https://api.deepseek.com/chat/completions"
            )
            return super().prepare(gateway, *args, **kwargs)

    class ForeignDictionary(dict):
        def items(self):
            pytest.fail("foreign delegated items")

        def __setitem__(self, key, value):
            pytest.fail("foreign delegated registry write")

    def factory():
        gateway = env.factory()
        if mutation == "send_subclass":
            gateway._prepared_requests = DoubleSend()
        elif mutation == "prepare_subclass":
            gateway._prepared_requests = EarlyPrepare()
        elif mutation == "replacement":
            gateway._prepared_requests = SimpleNamespace(prepare=pytest.fail, send=pytest.fail)
        elif mutation in {"send_instance", "prepare_instance"}:
            dispatcher = gateway._prepared_requests
            if mutation == "send_instance":
                send = dispatcher.send

                def double_send(gateway, request):
                    attempted.append("extra instance send")
                    gateway._post_chat_completion(request.body, endpoint=request.endpoint)
                    return send(gateway, request)

                dispatcher.send = double_send
            else:
                dispatcher.prepare = EarlyPrepare().prepare
        elif mutation == "router_instance":
            gateway._deepseek_router.resolve = lambda *args, **kwargs: pytest.fail(
                "foreign resolve"
            )
        elif mutation == "registry_dict":
            gateway._prepared_requests._issued.data = ForeignDictionary()
        elif mutation == "router_dict":
            gateway._deepseek_router._role_profiles = ForeignDictionary()
        else:
            gateway._prepared_requests._issued.get = lambda *args: pytest.fail("foreign get")
        return gateway

    with pytest.raises(CoverageRefusedError, match="unresolved_failure"):
        invoke(env, compose(env, gateway_factory=factory))
    assert not attempted and not env.requests and not env.budget.calls and not env.budget.receipts


def test_dispatcher_replaced_after_reservation_refuses_before_transport(env, monkeypatch):
    reserve = env.budget.reserve_model_call

    def replace_after_reserve(*args, **kwargs):
        result = reserve(*args, **kwargs)
        env.gates[-1]._prepared_requests.send = lambda *args: pytest.fail("extra transport")
        return result

    monkeypatch.setattr(env.budget, "reserve_model_call", replace_after_reserve)
    with pytest.raises(CoverageRefusedError):
        invoke(env)
    assert not env.requests and not env.budget.receipts and len(env.budget.calls) == 1
