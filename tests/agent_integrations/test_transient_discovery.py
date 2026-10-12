from agent_integrations.redis_transient_discovery import discover

from tests.agent_core.test_transient_output_contract import authorization, generation
from tests.agent_integrations.test_redis_transient_output import native as _native_fixture

native = _native_fixture


def test_atomic_descriptor_and_control_follow_fresh_activation_without_renewing_read_ttl(native):
    adapter, client, known = native
    auth = authorization(generation())
    known.append(auth)
    adapter._descriptor_source = lambda _: 9
    adapter.activate(auth)
    lane = adapter._keys(auth.scope)[0].removesuffix(":authority")
    result = discover(client, lane)
    assert result is not None
    descriptor, revision = result
    assert descriptor.scope == auth.scope and descriptor.fence == auth.lease_fence
    assert descriptor.request_sequence == 9
    assert revision
    key = lane + ":authority"
    before = client.pttl(key)
    assert discover(client, lane) == result
    assert client.pttl(key) <= before
    hints = client.xrange(key + ":control")
    assert len(hints) == 1
    assert hints[0][1] == {"generation": auth.scope.generation.generation_id}
    adapter.invalidate(auth.scope)
    assert discover(client, lane) is None
    assert len(client.xrange(key + ":control")) == 2
