"""Known digests use the existing exact read Port without preliminary getters."""

import pytest

from tests.agent_core.test_coverage_executor import executor, setup_execution


class VerifiedStore:
    def __init__(self, original):
        self.original = original
        self.getters = self.reads = 0
        self.damage = None

    def __getattr__(self, name):
        return getattr(self.original, name)

    def get_payload(self, identifier):
        self.getters += 1
        return self.original.get_payload(identifier)

    def read_payload_bytes_bounded(self, *args, **kwargs):
        return self.original.read_payload_bytes_bounded(*args, **kwargs)

    def store_payload_immutable(self, *args, **kwargs):
        return self.original.store_payload_immutable(*args, **kwargs)

    def read_payload_verified_bounded(self, identifier, *, session_id, digest, max_bytes):
        self.reads += 1
        stored = self.original.get_payload(identifier)
        assert stored.session_id == session_id and stored.sha256 == digest
        body = self.original.read_payload_bytes_bounded(identifier, max_bytes=max_bytes)
        if self.damage == "digest":
            stored = stored.model_copy(update={"sha256": "0" * 64})
        elif self.damage == "identity":
            stored = stored.model_copy(update={"uri": "artifact://foreign"})
        elif self.damage == "body":
            body += b"corrupt"
        elif self.damage == "retention":
            stored = stored.model_copy(update={"retained_until": stored.created_at})
        return stored, body


def test_exact_reader_reuses_one_read_and_legacy_stores_keep_working(tmp_path):
    env = setup_execution(tmp_path)
    store = VerifiedStore(env.artifacts)
    worker = executor(env, artifacts=store)
    assert store.reads == 1 and store.getters == 0  # Manifest initialization.
    expected, accepted = worker.execute_batch(fence=env.fence, batch_commits=True)
    assert expected == accepted == 3
    assert store.reads > 1
    # Unknown observation existence remains a genuine lookup, not a cache hit.
    assert store.getters > 0


@pytest.mark.parametrize("damage", ["digest", "identity", "body", "retention"])
def test_exact_reader_return_is_still_validated(tmp_path, damage):
    env = setup_execution(tmp_path)
    store = VerifiedStore(env.artifacts)
    store.damage = damage
    with pytest.raises(ValueError, match="conflicts"):
        executor(env, artifacts=store)
    assert store.reads == 1 and store.getters == 0
