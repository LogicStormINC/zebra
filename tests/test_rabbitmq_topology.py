import re
from pathlib import Path

import httpx
import pytest

from scripts.provision_rabbitmq import (
    BASE_PASSWORD_KEYS,
    PASSWORD_KEYS,
    SHADOW_PASSWORD_KEYS,
    SOURCE_BASE_PASSWORD_KEYS,
    SOURCE_PASSWORD_KEYS,
    SOURCE_SHADOW_PASSWORD_KEYS,
    prepare,
    prepare_shadow,
    prepare_source,
    provision,
    read_settings,
    source_topology,
    topology,
)


def test_prepare_is_private_and_never_overwrites(tmp_path):
    path = tmp_path / ".env"
    prepare(path)
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    settings = read_settings(path)
    assert len({settings[key] for key in PASSWORD_KEYS}) == len(PASSWORD_KEYS)
    with pytest.raises(FileExistsError):
        prepare(path)
    assert path.read_bytes() == original
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        read_settings(path)


def test_provision_roles_and_explicit_topology(monkeypatch):
    requests = []

    def handle(request):
        import json

        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(201)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(
            **kw,
            transport=httpx.MockTransport(handle),
        ),
    )
    settings = {key: "a" * 43 for key in PASSWORD_KEYS}
    settings["RABBITMQ_MANAGEMENT_PORT"] = "25673"
    provision(settings)
    for system in ("zebra", "trench"):
        spec = topology(system)
        permissions = dict(requests)[f"/api/permissions/{spec['vhost']}/{system}-consumer"]
        assert permissions["configure"] == permissions["write"] == "^$"
        assert "dlq" not in permissions["read"]
        policy = dict(requests)[f"/api/policies/{spec['vhost']}/ready-reliability"]
        assert policy["definition"]["dead-letter-strategy"] == "at-least-once"
        assert policy["definition"]["overflow"] == "reject-publish"
        relay = dict(requests)[f"/api/permissions/{spec['vhost']}/{system}-relay"]
        assert relay["read"] == relay["configure"] == "^$"
        for exchange in (
            spec["exchange"],
            spec["shadow_exchange"],
            spec["diagnostic_exchange"],
        ):
            assert re.fullmatch(relay["write"], exchange)
        for forbidden in (spec["dlx"], spec["dlq"], spec["diagnostic_queue"], "other.x"):
            assert not re.fullmatch(relay["write"], forbidden)
        assert not re.fullmatch(permissions["read"], spec["diagnostic_queue"])
        assert not re.fullmatch(permissions["read"], spec["shadow_queue"])
        shadow = dict(requests)[f"/api/permissions/{spec['vhost']}/{system}-shadow-consumer"]
        assert re.fullmatch(shadow["read"], spec["shadow_queue"])
        assert not re.fullmatch(shadow["read"], spec["queue"])
        diagnostic = dict(requests)[f"/api/queues/{spec['vhost']}/{spec['diagnostic_queue']}"]
        assert diagnostic == {"durable": True, "arguments": {"x-queue-type": "quorum"}}
        retention = dict(requests)[f"/api/policies/{spec['vhost']}/safe-diagnostic"]["definition"]
        assert retention == {
            "overflow": "reject-publish",
            "max-length-bytes": 4_194_304,
            "message-ttl": 604_800_000,
        }
        shadow_retention = dict(requests)[f"/api/policies/{spec['vhost']}/bounded-shadow"][
            "definition"
        ]
        assert shadow_retention == {
            "overflow": "reject-publish",
            "max-length-bytes": 1_048_576,
            "message-ttl": 86_400_000,
        }
        topics = [
            body
            for path, body in requests
            if path == f"/api/topic-permissions/{spec['vhost']}/{system}-relay"
        ]
        assert {body["exchange"] for body in topics} == {
            spec["exchange"],
            spec["shadow_exchange"],
            spec["diagnostic_exchange"],
        }
        for body in topics:
            route = (
                spec["routing_key"]
                if body["exchange"] == spec["exchange"]
                else (
                    spec["shadow_routing_key"]
                    if body["exchange"] == spec["shadow_exchange"]
                    else spec["diagnostic_routing_key"]
                )
            )
            assert re.fullmatch(body["write"], route)
            assert not re.fullmatch(body["write"], route + ".other")
    assert all("source.fetch" not in path for path, _ in requests)


def test_source_delivery_is_opt_in_with_independent_minimal_roles(monkeypatch):
    requests = []

    def handle(request):
        import json

        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(201)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)),
    )
    settings = {key: "a" * 43 for key in PASSWORD_KEYS + SOURCE_PASSWORD_KEYS}
    settings["RABBITMQ_MANAGEMENT_PORT"] = "25673"
    provision(settings, source_delivery=True)
    spec = source_topology()
    request_map = dict(requests)
    relay = request_map[f"/api/permissions/{spec['vhost']}/trench-source-relay"]
    consumer = request_map[f"/api/permissions/{spec['vhost']}/trench-source-consumer"]
    shadow = request_map[f"/api/permissions/{spec['vhost']}/trench-source-shadow-consumer"]
    assert relay["read"] == relay["configure"] == "^$"
    assert consumer["write"] == consumer["configure"] == "^$"
    assert re.fullmatch(consumer["read"], spec["queue"])
    assert not re.fullmatch(consumer["read"], spec["shadow_queue"])
    assert re.fullmatch(shadow["read"], spec["shadow_queue"])
    assert not re.fullmatch(shadow["read"], spec["queue"])
    assert not re.fullmatch(consumer["read"], spec["dlq"])
    topics = [
        body
        for path, body in requests
        if path == f"/api/topic-permissions/{spec['vhost']}/trench-source-relay"
    ]
    assert {(body["exchange"], body["write"]) for body in topics} == {
        (spec["exchange"], f"^{re.escape(spec['routing_key'])}$"),
        (spec["shadow_exchange"], f"^{re.escape(spec['shadow_routing_key'])}$"),
        (spec["diagnostic_exchange"], f"^{re.escape(spec['diagnostic_routing_key'])}$"),
    }
    assert (
        request_map[f"/api/policies/{spec['vhost']}/source-ready-reliability"]["definition"][
            "dead-letter-routing-key"
        ]
        == spec["dlq"]
    )
    trench_queues = {
        path for path, _body in requests if path.startswith(f"/api/queues/{spec['vhost']}/")
    }
    assert len(trench_queues) == 7


def test_source_credentials_are_opt_in_and_pair_validated(tmp_path):
    path = tmp_path / ".env"
    prepare(path, source_delivery=True)
    settings = read_settings(path)
    assert all(key in settings for key in SOURCE_PASSWORD_KEYS)
    path.write_text(path.read_text().replace("TRENCH_SOURCE_RABBIT_CONSUMER_PASSWORD=", "REMOVED="))
    with pytest.raises(ValueError, match="set"):
        read_settings(path)


def test_legacy_credentials_are_accepted_and_shadow_upgrade_is_atomic(tmp_path):
    path = tmp_path / ".env"
    prepare(path, source_delivery=True)
    legacy = (
        b"\n".join(
            line
            for line in path.read_bytes().splitlines()
            if not any(
                line.startswith(f"{key}=".encode())
                for key in SHADOW_PASSWORD_KEYS + SOURCE_SHADOW_PASSWORD_KEYS
            )
        )
        + b"\n"
    )
    path.write_bytes(legacy)
    path.chmod(0o600)
    before = read_settings(path)
    assert all(key in before for key in BASE_PASSWORD_KEYS + SOURCE_BASE_PASSWORD_KEYS)
    prepare_shadow(path)
    after_bytes = path.read_bytes()
    after = read_settings(path)
    assert after_bytes.startswith(legacy)
    assert path.stat().st_mode & 0o777 == 0o600
    assert {key: after[key] for key in BASE_PASSWORD_KEYS + SOURCE_BASE_PASSWORD_KEYS} == {
        key: before[key] for key in BASE_PASSWORD_KEYS + SOURCE_BASE_PASSWORD_KEYS
    }
    assert all(key in after for key in SHADOW_PASSWORD_KEYS + SOURCE_SHADOW_PASSWORD_KEYS)


def test_shadow_upgrade_failure_preserves_legacy_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    prepare(path)
    legacy = (
        b"\n".join(
            line
            for line in path.read_bytes().splitlines()
            if not any(line.startswith(f"{key}=".encode()) for key in SHADOW_PASSWORD_KEYS)
        )
        + b"\n"
    )
    path.write_bytes(legacy)
    path.chmod(0o600)

    def fail_replace(*_args):
        raise OSError("fixture replacement failure")

    monkeypatch.setattr("scripts.provision_rabbitmq.os.replace", fail_replace)
    with pytest.raises(OSError, match="fixture replacement"):
        prepare_shadow(path)
    assert path.read_bytes() == legacy
    assert list(tmp_path.iterdir()) == [path]


def test_legacy_settings_provision_formal_roles_without_shadow_user(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    prepare(path)
    path.write_bytes(
        b"\n".join(
            line
            for line in path.read_bytes().splitlines()
            if not any(line.startswith(f"{key}=".encode()) for key in SHADOW_PASSWORD_KEYS)
        )
        + b"\n"
    )
    path.chmod(0o600)
    requests = []

    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(201)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)),
    )
    provision(read_settings(path))
    assert any(path.endswith("/zebra-consumer") for path in requests)
    assert all("shadow-consumer" not in path for path in requests)


def test_source_credentials_alone_do_not_activate_topology(monkeypatch):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(201)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)),
    )
    settings = {key: "a" * 43 for key in PASSWORD_KEYS + SOURCE_PASSWORD_KEYS}
    settings["RABBITMQ_MANAGEMENT_PORT"] = "25673"
    provision(settings)
    assert all("source.fetch" not in path and "trench-source" not in path for path in paths)


def test_source_opt_in_rejects_missing_pair_before_any_broker_write(monkeypatch):
    called = False

    def client(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(httpx, "Client", client)
    settings = {key: "a" * 43 for key in PASSWORD_KEYS}
    settings["RABBITMQ_MANAGEMENT_PORT"] = "25673"
    with pytest.raises(ValueError, match="not configured"):
        provision(settings, source_delivery=True)
    assert not called


def test_prepare_source_atomically_preserves_existing_credentials(tmp_path):
    path = tmp_path / ".env"
    prepare(path)
    before = read_settings(path)
    prepare_source(path)
    after = read_settings(path)
    assert {key: after[key] for key in PASSWORD_KEYS} == {key: before[key] for key in PASSWORD_KEYS}
    assert all(key in after for key in SOURCE_PASSWORD_KEYS)
    unchanged = path.read_bytes()
    with pytest.raises(ValueError, match="already exist"):
        prepare_source(path)
    assert path.read_bytes() == unchanged and path.stat().st_mode & 0o777 == 0o600


def test_prepare_source_failure_leaves_no_partial_pair(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    prepare(path)
    original = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("fixture replacement failure")

    monkeypatch.setattr("scripts.provision_rabbitmq.os.replace", fail_replace)
    with pytest.raises(OSError, match="fixture replacement"):
        prepare_source(path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_compose_is_opt_in_pinned_and_loopback_only():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker/compose.rabbitmq.yml").read_text()
    assert "@sha256:" in compose
    assert compose.count('"127.0.0.1:') == 3
    assert "rabbitmq" not in (root / "docker/compose.application.yml").read_text().lower()
