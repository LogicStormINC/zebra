from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.leases import LeaseFence
from agent_core.domain.stream_admission import (
    RunStreamAdmission,
    StreamCapabilities,
    StreamMode,
    negotiate_stream_mode,
)
from agent_core.domain.transient_output import (
    MAX_TRANSIENT_FRAME_BYTES,
    TransientGeneration,
    TransientTextFrame,
    transient_category_allowed,
)
from agent_core.ports.live_event_fanout import LiveEventCursor
from agent_core.ports.transient_output import (
    TransientOutputBatch,
    TransientResumeCursor,
    TransientStreamScope,
    TransientWriterAuthorization,
)
from pydantic import ValidationError


def generation() -> TransientGeneration:
    return TransientGeneration.model_validate(
        dict(
            task_id=uuid4(), segment_id=uuid4(), turn_id=uuid4(), run_id="run-1",
            attempt_number=1, model_call_id="call-1", message_id="message:call-1",
            generation_id="generation-1", lease_fence=1,
        )
    )


def frame(identity: TransientGeneration, **changes: object) -> TransientTextFrame:
    return TransientTextFrame.model_validate(
        {**identity.model_dump(), "offset": 0, "content_delta": "Hello", "durable_anchor": 7,
         **changes}
    )


def scope(identity: TransientGeneration, namespace: str = "namespace-1") -> TransientStreamScope:
    return TransientStreamScope(
        deployment_namespace=namespace,
        authority_scope=OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="external"),
        generation=identity,
    )


def authorization(identity: TransientGeneration) -> TransientWriterAuthorization:
    now = datetime.now(UTC)
    return TransientWriterAuthorization(
        scope=scope(identity), lease_fence=LeaseFence(
            control_plane_epoch=uuid4(), fencing_token=identity.lease_fence,
            owner_instance_id="worker-1",
        ), gate_context_ref="verified-call-gate-1", issued_at=now,
        expires_at=now + timedelta(seconds=20), lease_expires_at=now + timedelta(seconds=25),
        grant_expires_at=now + timedelta(seconds=30),
    )


def test_frame_roundtrip_is_transient_and_has_no_authority_or_event_sequence() -> None:
    identity = generation()
    output = frame(identity, content_delta=" 你好🙂\n")
    assert TransientTextFrame.model_validate_json(output.wire_bytes()) == output
    assert output.generation == identity
    assert output.content_delta == " 你好🙂\n"
    assert not {"sequence", "event_id", "deployment_namespace", "namespace_id"} & set(
        output.model_dump()
    )
    assert output.offset == 0 and output.durable_anchor == 7


@pytest.mark.parametrize("changes", [
    {"sequence": 8}, {"namespace_id": "victim"}, {"kind": "reasoning_delta"},
    {"version": True}, {"version": 1}, {"offset": True}, {"offset": "1"},
    {"offset": -1}, {"durable_anchor": -1}, {"attempt_number": 0},
    {"lease_fence": False}, {"run_id": " run"}, {"generation_id": "bad\nidentity"},
    {"presentation": "final"}, {"content_delta": ""}, {"content_delta": {"reasoning": "secret"}},
])
def test_rejects_untrusted_frame_shape(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        frame(generation(), **changes)


@pytest.mark.parametrize("text", ["a", "中", "🙂", '"', "\n"])
def test_frame_budget_counts_utf8_envelope_and_json_escaping(text: str) -> None:
    identity = generation()
    empty_overhead = len(frame(identity, content_delta="a").wire_bytes()) - 1
    unit_bytes = len(frame(identity, content_delta=text).wire_bytes()) - empty_overhead
    count = (MAX_TRANSIENT_FRAME_BYTES - empty_overhead) // unit_bytes
    output = frame(identity, content_delta=text * count)
    assert len(output.wire_bytes()) <= MAX_TRANSIENT_FRAME_BYTES
    with pytest.raises(ValidationError, match="16KiB"):
        frame(identity, content_delta=text * (count + 1))


def test_publish_category_is_closed_and_not_authorization() -> None:
    assert not transient_category_allowed(event_type=EventType.MODEL_RESPONSE_DELTA)
    assert transient_category_allowed(
        event_type=EventType.MODEL_RESPONSE_DELTA, category="ordinary_public_text",
        coverage_mode=False,
    )
    for category in (None, "private_reasoning", "candidate", "public_expression", "new_event"):
        assert not transient_category_allowed(
            event_type=EventType.MODEL_RESPONSE_DELTA, category=category, coverage_mode=False,
        )
    for stage in ("public_expression", "reasoning", "private", "ordinary", "unknown"):
        assert not transient_category_allowed(
            event_type=EventType.MODEL_RESPONSE_DELTA, category="ordinary_public_text",
            response_stage=stage, coverage_mode=False,
        )
    for stage in (None, "candidate", "tool_loop"):
        assert transient_category_allowed(
            event_type=EventType.MODEL_RESPONSE_DELTA, category="ordinary_public_text",
            response_stage=stage, coverage_mode=False,
        )
    for event_type in EventType:
        if event_type is not EventType.MODEL_RESPONSE_DELTA:
            assert not transient_category_allowed(
                event_type=event_type, category="ordinary_public_text", coverage_mode=False,
            )
    assert not transient_category_allowed(
        event_type=EventType.MODEL_RESPONSE_DELTA, category="ordinary_public_text",
        coverage_mode=True,
    )


def test_admission_defaults_legacy_and_does_not_infer_activation_from_capability() -> None:
    compatible = StreamCapabilities(
        wire_version=2, provisional_draft_label=True, replace_message=True,
        reset_provisional=True, scoped_resume=True,
    )
    assert negotiate_stream_mode(capabilities=compatible) is StreamMode.LEGACY
    assert negotiate_stream_mode(capabilities=StreamCapabilities(), transient_enabled=True) is (
        StreamMode.LEGACY
    )
    assert negotiate_stream_mode(capabilities=compatible, transient_enabled=True) is (
        StreamMode.TRANSIENT_V2
    )
    legacy = RunStreamAdmission(task_id=uuid4(), run_id="run-1")
    assert legacy.mode is StreamMode.LEGACY
    v2 = RunStreamAdmission(
        task_id=uuid4(), run_id="run-1", mode=StreamMode.TRANSIENT_V2, capabilities=compatible,
    )
    v2.ensure_observer_compatible(compatible)
    with pytest.raises(ValueError, match="observer"):
        v2.ensure_observer_compatible(StreamCapabilities())
    with pytest.raises(ValidationError):
        v2.mode = StreamMode.LEGACY


@pytest.mark.parametrize("missing", [
    "provisional_draft_label", "replace_message", "reset_provisional", "scoped_resume",
])
def test_partial_capability_cannot_admit_v2(missing: str) -> None:
    capabilities = StreamCapabilities.model_validate({
        "wire_version": 2, "provisional_draft_label": True, "replace_message": True,
        "reset_provisional": True,
        "scoped_resume": True, missing: False,
    })
    with pytest.raises(ValueError, match="requires"):
        RunStreamAdmission(
            task_id=uuid4(), run_id="run", mode=StreamMode.TRANSIENT_V2,
            capabilities=capabilities,
        )


def test_scope_is_server_bound_and_deny_all_session_scope_is_rejected() -> None:
    identity = generation()
    with pytest.raises(ValidationError, match="outside authority"):
        TransientStreamScope(
            deployment_namespace="namespace-1", generation=identity,
            authority_scope=OpaqueAuthorityScope(
                authority_issuer="issuer", namespace_id="external", allowed_session_ids=(),
            ),
        )
    with pytest.raises(ValidationError):
        scope(identity, " namespace-1")


def test_writer_window_clips_to_grant_lease_and_ceiling() -> None:
    grant = authorization(generation())
    for deadline in (
        grant.issued_at, grant.lease_expires_at + timedelta(microseconds=1),
        grant.issued_at + timedelta(seconds=31),
    ):
        with pytest.raises(ValidationError, match="30-second"):
            TransientWriterAuthorization.model_validate(
                {**grant.model_dump(), "expires_at": deadline}
            )
    with pytest.raises(ValidationError, match="30-second"):
        TransientWriterAuthorization.model_validate({
            **grant.model_dump(), "grant_expires_at": grant.issued_at + timedelta(seconds=5),
        })
    with pytest.raises(ValidationError, match="timezone"):
        TransientWriterAuthorization.model_validate({
            **grant.model_dump(), "issued_at": grant.issued_at.replace(tzinfo=None),
        })


def test_writer_rejects_expired_before_issue_or_other_attempt_generation() -> None:
    identity = generation()
    grant = authorization(identity)
    grant.ensure_frame(frame(identity), now=grant.issued_at, current_fence=grant.lease_fence)
    for now in (grant.issued_at - timedelta(microseconds=1), grant.expires_at):
        with pytest.raises(ValueError, match="not current"):
            grant.ensure_frame(frame(identity), now=now, current_fence=grant.lease_fence)
    for key, value in (("attempt_number", 2), ("generation_id", "new"), ("lease_fence", 2),
                       ("run_id", "new-run")):
        with pytest.raises(ValueError, match="generation"):
            grant.ensure_frame(
                frame(identity, **{key: value}), now=grant.issued_at,
                current_fence=grant.lease_fence,
            )


def test_resume_positions_are_independent_and_scope_is_exact() -> None:
    identity = generation()
    binding = scope(identity)
    cursor = TransientResumeCursor(
        scope=binding, durable_sequence=7, durable_frame_index=2,
        live_cursor=LiveEventCursor("999-0"), live_offset=100,
    )
    assert cursor.durable_sequence == 7 and cursor.live_offset == 100
    cursor.ensure_scope(binding)
    for other in (scope(identity, "other-namespace"), scope(generation())):
        with pytest.raises(ValueError, match="another stream"):
            cursor.ensure_scope(other)
    with pytest.raises(ValidationError, match="requires a live cursor"):
        TransientResumeCursor(scope=binding, durable_sequence=7, live_offset=1)
    with pytest.raises(ValidationError):
        TransientResumeCursor(scope=binding, durable_sequence=True)


def test_batch_checks_bytes_scope_and_resync_before_delivery() -> None:
    identity = generation()
    cursor = TransientResumeCursor(scope=scope(identity), durable_sequence=7)
    TransientOutputBatch(frames=(frame(identity),), next_cursor=cursor)
    for frames, resync in (((frame(generation()),), False), ((frame(identity),), True)):
        with pytest.raises(ValidationError):
            TransientOutputBatch(frames=frames, next_cursor=cursor, resync_required=resync)
    full_frames = tuple(frame(identity, offset=index, content_delta="a" * 15_000)
                        for index in range(18))
    with pytest.raises(ValidationError, match="256KiB"):
        TransientOutputBatch(frames=full_frames, next_cursor=cursor)


def test_writer_exact_30_second_ceiling_independent_of_long_lease_and_grant() -> None:
    existing = authorization(generation())
    data = {
        **existing.model_dump(),
        "lease_expires_at": existing.issued_at + timedelta(minutes=5),
        "grant_expires_at": existing.issued_at + timedelta(minutes=5),
        "expires_at": existing.issued_at + timedelta(seconds=30),
    }
    grant = TransientWriterAuthorization.model_validate(data)
    assert (grant.expires_at - grant.issued_at).total_seconds() == 30
    with pytest.raises(ValidationError, match="30-second"):
        TransientWriterAuthorization.model_validate({
            **data, "expires_at": grant.expires_at + timedelta(microseconds=1),
        })


def test_batch_exact_100_frame_count_and_101_rejection() -> None:
    identity = generation()
    cursor = TransientResumeCursor(scope=scope(identity), durable_sequence=7)
    frames = tuple(frame(identity, offset=index) for index in range(101))
    assert len(TransientOutputBatch(frames=frames[:100], next_cursor=cursor).frames) == 100
    with pytest.raises(ValidationError):
        TransientOutputBatch(frames=frames, next_cursor=cursor)


def test_stable_existing_message_identity_and_draft_semantics() -> None:
    identity = generation()
    output = frame(identity)
    assert output.message_id == f"message:{output.model_call_id}"
    assert output.presentation == "provisional_draft"
    for value in ("", "message:unrelated-call", " message:call-1", "message:call\n1", "a" * 257):
        with pytest.raises(ValidationError):
            frame(identity, message_id=value)


def test_full_lease_fence_distinguishes_epoch_and_owner_with_equal_token() -> None:
    identity = generation()
    grant = authorization(identity)
    for change in ({"control_plane_epoch": uuid4()}, {"owner_instance_id": "worker-2"}):
        other_fence = LeaseFence.model_validate({**grant.lease_fence.model_dump(), **change})
        other_grant = TransientWriterAuthorization.model_validate({
            **grant.model_dump(), "lease_fence": other_fence,
        })
        assert other_grant != grant
        assert other_grant.lease_fence.fencing_token == grant.lease_fence.fencing_token
        with pytest.raises(ValueError, match="full lease fence is stale"):
            grant.ensure_frame(frame(identity), now=grant.issued_at, current_fence=other_fence)
    with pytest.raises(ValidationError, match="token must match"):
        TransientWriterAuthorization.model_validate({
            **grant.model_dump(), "lease_fence": {
                **grant.lease_fence.model_dump(), "fencing_token": identity.lease_fence + 1,
            },
        })
