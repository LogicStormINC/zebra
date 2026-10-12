"""Real native checkpoint publication avoids wrapper lookups, not I/O guards."""
# ruff: noqa: F401,F811

import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.sessions import SessionStatus
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_native_model import (
    NativeSemanticCoverageModel,
    qualified_checkpoint_publication,
)
from zebra_agent_worker.coverage_native_publication import NativeCoverageArtifacts

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_checkpoint_owner_no_lookup_and_retry_no_duplicate_event(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    active, publications, loads, retries = set(), 0, 0, 0
    previous = sys.getprofile()

    def compose(**kwargs):
        invocation = kwargs["invoke_or_replay"]
        # Exercise the retained standalone publisher contract explicitly; the
        # unified owner has separate native producer/settlement regressions.
        invocation._evidence_operation = None
        wrapper = invocation.artifacts
        assert type(wrapper) is NativeCoverageArtifacts
        assert qualified_checkpoint_publication(wrapper, invocation._preparation_boundary)
        assert not qualified_checkpoint_publication(wrapper, lambda: invocation._boundary())
        with monkeypatch.context() as patch:
            patch.setattr(wrapper.store, "sync_events", lambda: None)
            assert not qualified_checkpoint_publication(wrapper, invocation._preparation_boundary)
        with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
            wrapper.publish(
                uuid4(), MODEL_CHECKPOINT_KIND, b"not a checkpoint", 1024,
                invocation._preparation_boundary, invocation.binding.snapshot.expires_at,
                mime_type="application/json",
            )
        return NativeSemanticCoverageModel(**kwargs)

    def observe(frame, event, result):
        nonlocal publications, loads, retries
        if frame.f_code is NativeCoverageArtifacts._publish.__code__:
            if (frame.f_locals["kind"] == MODEL_CHECKPOINT_KIND
                    and frame.f_locals["body"] != b"not a checkpoint"):
                if event == "call":
                    active.add(id(frame))
                    publications += 1
                elif event == "return":
                    active.discard(id(frame))
                    assert result == f'artifact://{frame.f_locals["identifier"]}'
                    # Profiling callbacks do not recursively profile themselves.
                    # Retry while actual Worker authority is still live.
                    wrapper, values = frame.f_locals["self"], frame.f_locals
                    before = env.events.list_for_session(env.session)
                    retry = wrapper.publish(
                        values["identifier"], values["kind"], values["body"],
                        values["maximum"], values["validate"], values["expires_at"],
                        mime_type=values["mime_type"],
                    )
                    assert retry == result
                    assert env.events.list_for_session(env.session) == before
                    retries += 1
        if event == "call" and active and frame.f_code is CoverageArtifacts.load_payload.__code__:
            loads += 1
        if previous is not None:
            previous(frame, event, result)

    monkeypatch.setattr(dispatch, "NativeSemanticCoverageModel", compose)
    handoff = native_handoff(env)
    sys.setprofile(observe)
    try:
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    finally:
        sys.setprofile(previous)
    assert result.session.status is SessionStatus.COMPLETED
    assert publications > 0 and retries == publications and loads == 0


@pytest.mark.parametrize("variant", ["lambda", "partial", "callable", "foreign_owner", "manifest"])
def test_unknown_publication_callback_uses_generic_without_introspection(monkeypatch, variant):
    class HostileCallable:
        @property
        def __self__(self):
            pytest.fail("unknown callable introspection dispatched a callback")

        def __call__(self):
            return datetime.now(UTC)

    def now():
        return datetime.now(UTC)
    callback = {
        "lambda": lambda: datetime.now(UTC), "partial": partial(now),
        "callable": HostileCallable(),
        "foreign_owner": datetime.now, "manifest": now,
    }[variant]
    generic = Mock(return_value="generic path")
    monkeypatch.setattr(CoverageArtifacts, "_publish", generic)
    wrapper = NativeCoverageArtifacts(Mock(), uuid4(), nullcontext())
    assert not qualified_checkpoint_publication(wrapper, callback)
    assert wrapper._publish(
        uuid4(), "coverage_manifest" if variant == "manifest" else MODEL_CHECKPOINT_KIND,
        b"body", 1024, callback, datetime.now(UTC),
    ) == "generic path"
    generic.assert_called_once()
