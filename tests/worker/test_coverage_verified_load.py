"""Shared loader reuses native verified reads without relaxing post-I/O checks."""
# ruff: noqa: F811

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_integrations.coverage_model_invocation import CoverageModelInvocation
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from zebra_agent_worker.coverage_prepared_reads import PreparedCoverageReads

from tests.worker.test_coverage_artifacts import (  # noqa: F401
    dsn,
    facade,
    postgres_dsn,
    postgres_env,
    publication,
)


def loader(env, current, verified):
    store = current if verified else SimpleNamespace(
        get_payload=current.get_payload,
        inspect_payload=current.inspect_payload,
        read_payload_bytes_bounded=current.read_payload_bytes_bounded,
    )
    return CoverageArtifacts(store, env.binding.session_id, nullcontext())


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("known", [False, True])
def test_shared_load_guards_are_fresh_and_reuse_verified_port(
    publication, monkeypatch, verified, known,
):
    env = publication
    current = facade(env)
    stored = current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    checks = []
    current.check_authority = lambda: checks.append("check")
    original = env.objects.read_version_verified

    def read(*args):
        checks.append("physical")
        return original(*args)

    monkeypatch.setattr(env.objects, "read_version_verified", read)
    result = loader(env, current, verified).load_payload(
        env.artifact_id, env.payload.kind, len(env.payload.payload), datetime.now(UTC),
        mime_type=env.payload.mime_type,
        expected_digest=sha256(env.payload.payload).hexdigest() if known else None,
    )
    assert result[0] == stored
    assert result[1] == env.payload.payload
    assert checks == (["check", "physical", "check"] if verified else ["check"] + [
        "check", "physical", "check",
    ] + ["check"])


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize("known", [False, True])
def test_shared_load_refuses_revocation_during_physical_read(
    publication, monkeypatch, verified, known,
):
    env = publication
    current = facade(env)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    revoked = False
    original = env.objects.read_version_verified
    reads = []

    def check():
        if revoked:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)

    def read(*args):
        nonlocal revoked
        result = original(*args)
        reads.append(result)
        revoked = True
        return result

    current.check_authority = check
    monkeypatch.setattr(env.objects, "read_version_verified", read)
    with pytest.raises(CoverageRefusedError):
        loader(env, current, verified).load_payload(
            env.artifact_id, env.payload.kind, len(env.payload.payload), datetime.now(UTC),
            mime_type=env.payload.mime_type,
            expected_digest=sha256(env.payload.payload).hexdigest() if known else None,
        )
    assert reads == [env.payload.payload]


@pytest.mark.parametrize("corrupt", ["metadata", "digest", "length"])
@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("scoped", [False, True])
def test_shared_load_checks_full_returned_metadata_and_bytes(
    publication, monkeypatch, corrupt, known, scoped,
):
    env = publication
    current = facade(env)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    store = current if scoped else SimpleNamespace(
        get_payload=current.get_payload,
        read_payload_verified_bounded=current.read_payload_verified_bounded,
    )
    original = (PreparedCoverageReads.read_payload_verified_bounded if scoped else
                store.read_payload_verified_bounded)

    def read(*args, **kwargs):
        metadata, body = original(*args, **kwargs)
        if corrupt == "metadata":
            metadata = metadata.model_copy(update={"mime_type": "text/plain"})
        elif corrupt == "digest":
            body = b"!" + body[1:]
        else:
            body += b"!"
        return metadata, body

    monkeypatch.setattr(PreparedCoverageReads if scoped else store,
                        "read_payload_verified_bounded", read)
    with pytest.raises(CoverageRefusedError):
        CoverageArtifacts(store, env.binding.session_id, nullcontext()).load_payload(
            env.artifact_id, env.payload.kind, len(env.payload.payload), datetime.now(UTC),
            mime_type=env.payload.mime_type,
            expected_digest=sha256(env.payload.payload).hexdigest() if known else None,
        )


@pytest.mark.parametrize("known", [False, True])
def test_model_load_uses_returned_metadata_without_extra_get(publication, monkeypatch, known):
    env = publication
    current = facade(env)
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    checks = []
    current.check_authority = lambda: checks.append("check")
    invocation = CoverageModelInvocation.__new__(CoverageModelInvocation)
    invocation.artifacts = loader(env, current, True)
    invocation._retained_until = None
    invocation._time = lambda: datetime.now(UTC)
    assert invocation._load(env.artifact_id, env.payload.kind,
                            expected=env.payload.payload if known else None) == env.payload.payload
    assert len(checks) == 2
    # A second boundary is another physical read with fresh pre/post checks.
    assert invocation._load(env.artifact_id, env.payload.kind,
                            expected=env.payload.payload if known else None) == env.payload.payload
    assert len(checks) == 4


@pytest.mark.parametrize("known", [False, True])
def test_model_load_cannot_renew_original_retention_during_read(publication, monkeypatch, known):
    env = publication
    current = facade(env)
    stamp = datetime.now(UTC)
    env.payload = env.payload.model_copy(update={"retained_until": stamp + timedelta(seconds=40)})
    current.store_payload_immutable(env.payload, artifact_id=env.artifact_id)
    invocation = CoverageModelInvocation.__new__(CoverageModelInvocation)
    invocation.artifacts = loader(env, current, True)
    invocation.binding = SimpleNamespace(snapshot=SimpleNamespace(
        as_of=stamp - timedelta(seconds=1), expires_at=stamp + timedelta(seconds=500),
    ))
    invocation.policy = SimpleNamespace(
        started_at=stamp - timedelta(seconds=1), deadline=stamp + timedelta(seconds=500),
    )
    invocation._retained_until = stamp + timedelta(seconds=10)
    invocation.now = lambda: stamp
    assert invocation._load(env.artifact_id, env.payload.kind,
                            expected=env.payload.payload if known else None) == env.payload.payload
    assert invocation._retained_until == stamp + timedelta(seconds=10)
    original = env.objects.read_version_verified

    def slow_read(*args):
        nonlocal stamp
        body = original(*args)
        stamp += timedelta(seconds=11)
        return body

    monkeypatch.setattr(env.objects, "read_version_verified", slow_read)
    with pytest.raises(CoverageRefusedError) as caught:
        invocation._load(env.artifact_id, env.payload.kind,
                         expected=env.payload.payload if known else None)
    assert caught.value.reason is CoverageRefusalReason.ARTIFACT_UNAVAILABLE
