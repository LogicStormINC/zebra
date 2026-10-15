"""Prefetch warms public keys, retaining TTL, rotation and native I/O bounds."""

from time import monotonic

import pytest
from agent_security import CachingJwksKeyResolver

from tests.agent_security.test_jwks_bounds import jwks_server, token

native_jwks = jwks_server


def test_prefetch_reuses_existing_cache_and_preserves_rotation(native_jwks):
    uri, key, calls, _, _ = native_jwks
    resolver = CachingJwksKeyResolver()
    resolver.prefetch(uri + "/rotating", deadline=monotonic() + 1)
    resolver.prefetch(uri + "/rotating", deadline=monotonic() + 1)
    assert resolver.resolve(uri + "/rotating", token(key), deadline=monotonic() + 1)
    assert calls == ["/rotating"]
    assert resolver.resolve(uri + "/rotating", token(key, "rotated"), deadline=monotonic() + 1)
    assert calls == ["/rotating", "/rotating"]
    stored_at, keys = resolver._sets[uri + "/rotating"]
    resolver._sets[uri + "/rotating"] = (stored_at - resolver.cache_lifespan_seconds - 1, keys)
    resolver.prefetch(uri + "/rotating", deadline=monotonic() + 1)
    assert calls == ["/rotating"] * 3


def test_prefetch_timeout_does_not_cache_partial_keys(native_jwks):
    uri, _, _, _, _ = native_jwks
    resolver = CachingJwksKeyResolver()
    started = monotonic()
    with pytest.raises(TimeoutError):
        resolver.prefetch(uri + "/drip", deadline=started + 0.3)
    assert monotonic() - started < 0.8
    assert not resolver._sets


def test_prefetch_uses_existing_cache_capacity_and_lock_deadline(monkeypatch):
    resolver = CachingJwksKeyResolver()
    monkeypatch.setattr(resolver, "_fetch", lambda *_: object())
    for index in range(40):
        resolver.prefetch(f"https://keys-{index}.example/keys", deadline=monotonic() + 1)
    assert len(resolver._sets) == 32
    resolver._lock.acquire()
    try:
        with pytest.raises(TimeoutError):
            resolver.prefetch("https://keys.example/keys", deadline=monotonic() + 0.02)
    finally:
        resolver._lock.release()
