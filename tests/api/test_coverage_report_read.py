"""Fresh report authority and real certified storage; no live Host claim."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.host_connectors import HostConnectorProfileVersion
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.coverage_report_authority import current_report_profile, validate_report_grant
from zebra_agent_api.coverage_report_read import _composition, read_coverage_report

from tests.agent_storage.test_command_wakeup import _binding
from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_dispatch import native_handoff, native_worker  # noqa: F401


def authority():
    task = _binding(str(uuid4()))
    host = task.host_capability.host_context.model_copy(
        update={
            "resource_refs": (
                HostResourceRef(type="principal", id="user-a"),
                HostResourceRef(type="trench.history", id="history"),
            ),
            "scopes": ("history.read", "artifact.read"),
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
    )
    task = TaskBindingSnapshot.model_validate(
        task.model_dump()
        | {
            "host_capability": task.host_capability.model_dump() | {"host_context": host},
        }
    )
    grant = VerifiedHostGrant(
        host, host.grant_id, JwtAlgorithm.RS256, task.host_capability.authority_issuer, "user-a"
    )
    return task, grant


def test_fresh_read_authority_does_not_require_old_execution_grant_live():
    task, grant = authority()
    old = task.host_capability.host_context.model_copy(
        update={
            "expires_at": datetime.now(UTC) - timedelta(days=1),
            "scopes": ("agent.run",),
        }
    )
    task = task.model_copy(
        update={
            "host_capability": task.host_capability.model_copy(
                update={"host_context": old},
            )
        }
    )
    validate_report_grant(task, grant, history_ref="history")


@pytest.mark.parametrize(
    "field,value",
    [
        ("host_app_id", "other"),
        ("namespace_id", "other"),
        ("workspace_ref", "other"),
        ("origin", "https://other.example"),
        ("scopes", ("history.read",)),
        ("scopes", ("artifact.read",)),
        ("expires_at", None),
        ("expires_at", datetime(2000, 1, 1, tzinfo=UTC)),
        (
            "resource_refs",
            (
                HostResourceRef(type="principal", id="other"),
                HostResourceRef(type="trench.history", id="history"),
            ),
        ),
        (
            "resource_refs",
            (
                HostResourceRef(type="principal", id="user-a"),
                HostResourceRef(type="trench.history", id="other"),
            ),
        ),
        ("resource_refs", (HostResourceRef(type="trench.history", id="history"),)),
        (
            "resource_refs",
            (
                HostResourceRef(type="principal", id="user-a"),
                HostResourceRef(type="trench.history", id="history"),
                HostResourceRef(type="trench.history", id="second"),
            ),
        ),
    ],
)
def test_mismatched_read_grant_is_refused(field, value):
    task, grant = authority()
    with pytest.raises(PermissionError):
        validate_report_grant(
            task,
            replace(
                grant,
                context=grant.context.model_copy(
                    update={field: value},
                ),
            ),
            history_ref="history",
        )


@pytest.mark.parametrize(
    "changes", [{"authority_issuer": "https://other.example"}, {"grant_id": "wrong"}]
)
def test_verified_wrapper_identity_is_not_ignored(changes):
    task, grant = authority()
    with pytest.raises(PermissionError):
        validate_report_grant(task, replace(grant, **changes), history_ref="history")


def test_report_requires_composed_cloud_storage_and_verified_grant():
    api = SimpleNamespace(settings=SimpleNamespace(deployment="local"), stores=object())
    with pytest.raises(RuntimeError):
        _composition(api)
    with pytest.raises(PermissionError):
        read_coverage_report(api, str(uuid4()), None)


def profile(host_app_id="trench", base_uri="https://trench.example"):
    return HostConnectorProfileVersion(
        host_app_id=host_app_id,
        connector_id=host_app_id,
        profile_revision=1,
        base_uri=base_uri,
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        supported_protocol_versions=("1",),
        workload_identity_ref="worker",
        credential_ref="fixture-host-credential",
    )


@pytest.mark.parametrize(
    "failure", ["task", "issuer", "inactive", "origin", "policy", "connector", "profile", "revoked"]
)
def test_current_native_registry_checks_are_read_only_and_fail_closed(monkeypatch, failure):
    import zebra_agent_api.coverage_report_authority as checks

    task, grant = authority()
    pinned = profile()
    task = task.model_copy(
        update={
            "host_capability": task.host_capability.model_copy(
                update={
                    "connector_id": pinned.connector_id,
                    "connector_profile_digest": pinned.profile_digest,
                }
            )
        }
    )
    control = SimpleNamespace(
        deployment_namespace="deployment",
        _database=SimpleNamespace(_dsn="unused"),
        load_task_binding=lambda _: None if failure == "task" else task,
    )
    registry = SimpleNamespace(
        active=failure != "inactive",
        issuer="other" if failure == "issuer" else grant.authority_issuer,
        allowed_origins=() if failure == "origin" else (grant.context.origin,),
        algorithms=("RS256",),
        policy_version="other" if failure == "policy" else grant.context.policy_version,
    )
    monkeypatch.setattr(
        checks,
        "PostgresHostAuthorityStore",
        lambda *args, **kwargs: SimpleNamespace(get_registry=lambda **kwargs: registry),
    )
    from agent_core.domain.host_connectors import HostConnectorStatus

    if failure == "revoked":
        pinned = pinned.model_copy(update={"status": HostConnectorStatus.REVOKED})
    monkeypatch.setattr(
        checks,
        "PostgresHostConnectorRegistry",
        lambda *args, **kwargs: SimpleNamespace(
            resolve_binding=lambda *args: None
            if failure == "connector"
            else SimpleNamespace(active=True, connector_id="trench", profile_revision=1),
            get_profile=lambda *args: None if failure == "profile" else pinned,
        ),
    )
    with pytest.raises(PermissionError):
        current_report_profile(
            SimpleNamespace(cloud_control=control),
            TaskId(UUID(task.task_id)),
            task,
            grant,
            history_ref="history",
            dsn="unused",
            deployment="deployment",
        )


@pytest.fixture
def report_worker(monkeypatch, request):
    """Pin the real admission's profile/owner before any original proof exists."""
    import tests.agent_integrations.test_coverage_snapshot_v2 as neutral
    import tests.worker.coverage_model_cloud_fixtures as fixtures

    params = getattr(getattr(request.node, "callspec", None), "params", {})
    mode = params.get("model_cloud", 600)
    is_v2 = isinstance(mode, dict) and mode.get("v2", False)
    pinned = profile("archive", "https://archive.example") if is_v2 else profile()
    if is_v2:
        pinned = pinned.model_copy(
            update={
                "manifest_binding_policy": "declared",
                "manifest_path": "/capabilities",
                "invoke_path_template": "/execute",
            }
        )
        monkeypatch.setattr(
            neutral,
            "V2_AUTHORITY",
            neutral.V2_AUTHORITY.model_copy(
                update={
                    "resource_refs": (
                        *neutral.V2_AUTHORITY.resource_refs,
                        HostResourceRef(type="principal", id="user-a"),
                    ),
                    "scopes": (*neutral.V2_AUTHORITY.scopes, "artifact.read"),
                }
            ),
        )
    monkeypatch.setattr(
        fixtures,
        "AUTHORITY",
        fixtures.AUTHORITY.model_copy(
            update={
                "resource_refs": (
                    *fixtures.AUTHORITY.resource_refs,
                    HostResourceRef(type="principal", id="user-a"),
                ),
                "scopes": (*fixtures.AUTHORITY.scopes, "artifact.read"),
            }
        ),
    )
    original = fixtures._binding

    def bound(*args, **kwargs):
        value = original(*args, **kwargs)
        return value.model_copy(
            update={
                "host_capability": value.host_capability.model_copy(
                    update={"connector_profile_digest": pinned.profile_digest},
                )
            }
        )

    monkeypatch.setattr(fixtures, "_binding", bound)
    env = request.getfixturevalue("native_worker")
    from agent_core.domain.host_connectors import HostConnectorBinding
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.host_manifest_freeze import store_frozen_manifest

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    registry = PostgresHostConnectorRegistry(env.dsn, deployment_namespace=NAMESPACE)
    registry.publish_profile(pinned)
    registry.bind(
        HostConnectorBinding(
            host_app_id=pinned.host_app_id,
            namespace_id="ns",
            connector_id=pinned.connector_id,
            profile_revision=1,
            binding_revision=1,
        )
    )
    manifest = env.host_source.host.manifest
    store_frozen_manifest(
        env.dsn,
        deployment_namespace=NAMESPACE,
        manifest_digest=manifest.digest,
        connector_id=pinned.connector_id,
        profile_revision=1,
        manifest_payload=manifest.to_payload(),
    )
    return env


@pytest.mark.parametrize("model_cloud", [600, {"v2": True}], indirect=True)
def test_native_reader_returns_only_certified_original_bytes_and_rechecks_host(
    report_worker,
    monkeypatch,
    model_cloud,  # noqa: F811
):
    from agent_core.domain.sessions import SessionStatus
    from agent_storage.postgres.direct_control import PostgresDirectControl
    from zebra_agent_api.app import ZebraAgentApi

    from tests.worker.coverage_model_cloud_fixtures import NAMESPACE

    env = report_worker
    for _ in range(2):
        handoff = native_handoff(env)
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    api = ZebraAgentApi(
        database_path=None,
        settings=replace(env.service._settings, database_url=env.dsn),
        _stores=env.stores,
        cloud_control=PostgresDirectControl(env.dsn, deployment_namespace=NAMESPACE),
    )
    grant = VerifiedHostGrant(
        env.host,
        env.host.grant_id,
        JwtAlgorithm.RS256,
        env.task_binding.host_capability.authority_issuer,
        "user-a",
    )
    before = len(env.native_requests)
    certificate, ref, body = read_coverage_report(api, str(TaskId(env.session)), grant)
    import hashlib

    assert hashlib.sha256(body).hexdigest() == certificate.report_digest
    assert ref == result.attempt_result.metadata["coverage_report_ref"]
    calls = env.native_requests[before:]
    assert 3 <= len(calls) <= 8
    if env.host.host_app_id == "archive":
        import json

        assert all(call.url.path == "/execute" for call in calls)
        assert all(json.loads(call.content)["toolName"] == "dataset.snapshot.get" for call in calls)
    else:
        assert all("dataset.snapshot.get" in str(call.url) for call in calls)
    import zebra_agent_api.http as report_http
    from fastapi.testclient import TestClient

    authentications = []

    class Authorizer:
        allowed_origins = (grant.context.origin,)

        def authorize(self, request):
            authentications.append(request.method)
            assert request.before_consume is not None
            request.before_consume(grant)
            return grant

    monkeypatch.setattr(report_http, "create_app", lambda *args, **kwargs: api)
    client = TestClient(
        report_http.create_http_app(
            settings=api.settings,
            host_grant_authorizer=Authorizer(),
        )
    )
    path = f"/tasks/{env.session}/coverage/report"
    for method in ("GET", "HEAD"):
        response = client.request(method, path, headers={"Authorization": "Bearer fixture"})
        assert response.status_code == 200, response.text
        assert response.content == (body if method == "GET" else b"")
        assert response.headers["x-coverage-report-sha256"] == certificate.report_digest
        assert response.headers["content-length"] == str(len(body))
    assert authentications == ["GET", "HEAD"]
    from agent_integrations.host_tools import HostToolTransportError
    from agent_integrations.host_tools.http import HttpHostToolTransport

    def timed_out(*args, **kwargs):
        raise HostToolTransportError("private Host transport", reason="timeout")

    with monkeypatch.context() as scoped:
        scoped.setattr(HttpHostToolTransport, "request", timed_out)
        response = client.get(path, headers={"Authorization": "Bearer fixture"})
        assert response.status_code == 503
        assert b"private Host transport" not in response.content
    original = env.wire.mutate
    reads = []

    def revoke_during_proof(name, value):
        reads.append(name)
        return {**value, "status": "revoked"} if len(reads) >= 3 else original(name, value)

    env.wire.mutate = revoke_during_proof
    with pytest.raises(ValueError):
        read_coverage_report(api, str(env.session), grant)
    assert len(reads) == 3
    # Proof reads may take time; entitlement is checked again at the final gate.
    env.wire.mutate = lambda name, value: {**value, "status": "revoked"}
    with pytest.raises(ValueError):
        read_coverage_report(api, str(env.session), grant)


def neutral_authority():
    from agent_core.domain.coverage_contracts import CoverageContract

    from tests.agent_core.test_coverage_task_admission import admission

    contract = CoverageContract.model_validate(
        admission().contract.model_dump(mode="json")
        | {
            "schema_version": 2,
            "dataset": "catalog.documents",
            "dataset_revision": "2026-10",
            "source": {
                "protocol": "coverage-source/2",
                "resource_type": "catalog.collection",
                "read_scope": "catalog.read",
                "create_scope": "catalog.snapshot.write",
            },
            "scope": {"selection_ref": "collection-selection", "selection_digest": "a" * 64},
        }
    )
    task, grant = authority()
    source = HostResourceRef(type="catalog.collection", id="collection-1")
    host = grant.context.model_copy(
        update={
            "host_app_id": "catalog",
            "scopes": ("catalog.read", "artifact.read"),
            "resource_refs": (HostResourceRef(type="principal", id="user-a"), source),
        }
    )
    task = task.model_copy(
        update={
            "host_capability": task.host_capability.model_copy(
                update={
                    "host_app_id": "catalog",
                    "host_context": host,
                }
            )
        }
    )
    grant = replace(grant, context=host)
    return task, grant, contract, source


def test_neutral_report_uses_frozen_source_read_scope_without_write_permission():
    task, grant, contract, source = neutral_authority()
    validate_report_grant(task, grant, contract=contract, source_ref=source)
    assert "history.read" not in grant.context.scopes
    assert "catalog.snapshot.write" not in grant.context.scopes


@pytest.mark.parametrize(
    "failure",
    [
        "source_scope",
        "artifact_scope",
        "resource_id",
        "resource_type",
        "extra_resource",
        "principal",
        "subject",
        "issuer",
        "workspace",
        "namespace",
        "expiry",
        "legacy_scope",
    ],
)
def test_neutral_report_never_borrows_other_source_or_legacy_permissions(failure):
    task, grant, contract, source = neutral_authority()
    context = grant.context
    updates = {
        "source_scope": {"scopes": ("artifact.read",)},
        "artifact_scope": {"scopes": ("catalog.read",)},
        "resource_id": {
            "resource_refs": (
                HostResourceRef(type="principal", id="user-a"),
                HostResourceRef(type="catalog.collection", id="other"),
            )
        },
        "resource_type": {
            "resource_refs": (
                HostResourceRef(type="principal", id="user-a"),
                HostResourceRef(type="other.collection", id="collection-1"),
            )
        },
        "extra_resource": {
            "resource_refs": (
                *context.resource_refs,
                HostResourceRef(type="catalog.collection", id="other"),
            )
        },
        "principal": {"resource_refs": (HostResourceRef(type="principal", id="other"), source)},
        "workspace": {"workspace_ref": "other"},
        "namespace": {"namespace_id": "other"},
        "expiry": {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        "legacy_scope": {"scopes": ("history.read", "artifact.read")},
    }
    if failure == "subject":
        grant = replace(grant, subject_ref="other")
    elif failure == "issuer":
        grant = replace(grant, authority_issuer="https://other.example")
    else:
        grant = replace(grant, context=context.model_copy(update=updates[failure]))
    with pytest.raises(PermissionError):
        validate_report_grant(task, grant, contract=contract, source_ref=source)


def test_report_rejects_cross_owner_before_reading_source_metadata(monkeypatch):
    from zebra_agent_api import coverage_report_read as reads

    task, grant, _, _ = neutral_authority()
    called = []
    monkeypatch.setattr(reads, "_composition", lambda _: ("unused", "deployment", None))
    monkeypatch.setattr(reads, "_run", lambda *_: called.append("source lookup"))
    control = SimpleNamespace(
        deployment_namespace="deployment",
        _database=SimpleNamespace(_dsn="unused"),
        load_task_binding=lambda _: task,
    )
    with pytest.raises(PermissionError):
        reads._read_coverage_report(
            SimpleNamespace(cloud_control=control),
            task.task_id,
            replace(grant, subject_ref="other"),
            float("inf"),
        )
    assert called == []


def test_real_preconsume_callback_accepts_only_exact_report_owner():
    from zebra_agent_api.http_host_auth import _TargetRejected, validate_host_target

    task, grant, _, _ = neutral_authority()
    control = SimpleNamespace(deployment_namespace="deployment", load_task_binding=lambda _: task)
    api = SimpleNamespace(
        stores=SimpleNamespace(deployment_namespace="deployment"),
        cloud_control=control,
    )
    path = f"/tasks/{task.task_id}/coverage/report"
    # No agent.run/thread/run claims are needed for certified read-only downloads.
    for method in ("GET", "HEAD"):
        validate_host_target(api, path, method, None, grant)
        with pytest.raises(_TargetRejected) as denied:
            validate_host_target(api, path, method, None, replace(grant, subject_ref="other"))
        assert denied.value.response.status_code == 404
    # The exception must never apply to a mutation or another Task route.
    for method, route in (("POST", path), ("GET", path + "/extra")):
        with pytest.raises(_TargetRejected):
            validate_host_target(api, route, method, None, grant)
