"""Real Broker RS256 envelopes must authorize the bound opaque Host thread."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.task_bindings import host_context_digest, require_task_host_context
from zebra_agent_api.routes import RouteRequest
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_api.tenant_guard import task_access_response, tenant_scope_response
from zebra_host_grant_broker.grant_minting import ExchangeRequest, mint_grant
from zebra_host_grant_broker.trench_session import TrenchViewer

from tests.host_grant_broker.test_grant_broker import _key, _settings, _verify_with_zebra

TASK = "11111111-1111-4111-8111-111111111111"
THREAD = "trench-bootstrap-opaque-case-sensitive-A"


@pytest.fixture(scope="module")
def broker():
    key = _key()
    return key, _settings(key)


def verified(broker, *, thread=THREAD, run="bootstrap:opaque", now=None, resources=None):
    key, settings = broker
    token = mint_grant(
        settings,
        key,
        ExchangeRequest("zebra", thread, run, ("agent.run", "event.read", "artifact.read")),
        TrenchViewer(user_id="user-a", workspace_id="workspace-a", active_source_ids=frozenset()),
        now=now,
    )
    if resources is not None:
        claims = jwt.decode(
            token,
            key.public_key(),
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
        claims["resource_refs"] = [ref.model_dump(by_alias=True) for ref in resources]
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": settings.key_id})
    return _verify_with_zebra(token, settings, key)


def binding_for(grant, *, task=TASK):
    return _build_binding_snapshot(
        task,
        host_context=grant.context,
        verified_host_grant=grant,
        definition_snapshot_digest="a" * 64,
    )


def app_for(binding):
    return SimpleNamespace(
        stores=SimpleNamespace(
            deployment_namespace="test-deployment",
            sessions=SimpleNamespace(
                get_session=lambda _: SimpleNamespace(namespace_id="trench-prod")
            ),
        ),
        cloud_control=SimpleNamespace(
            deployment_namespace="test-deployment",
            load_task_binding=lambda _: binding,
        ),
    )


@pytest.mark.parametrize(
    "thread", ["foreign-thread", TASK, "trench-bootstrap-opaque-case-sensitive-a"]
)
def test_same_principal_wrong_thread_is_denied(broker, thread):
    binding = binding_for(verified(broker))
    denied = task_access_response(app_for(binding), TASK, verified(broker, thread=thread).context)
    assert denied is not None and denied.status_code == 404


@pytest.mark.parametrize("refs", [(), (HostResourceRef(type="thread", id="second"),)])
def test_missing_or_ambiguous_thread_is_denied(broker, refs):
    grant = verified(broker)
    resources = (
        tuple(ref for ref in grant.context.resource_refs if ref.resource_type != "thread") + refs
    )
    if refs:
        resources += (HostResourceRef(type="thread", id=THREAD),)
    context = verified(broker, resources=resources).context
    denied = task_access_response(app_for(binding_for(grant)), TASK, context)
    assert denied is not None and denied.status_code == 404


def test_correct_opaque_thread_allows_new_run_and_ignores_old_execution_expiry(broker):
    grant = verified(broker)
    binding = binding_for(grant)
    old = grant.context.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    binding = binding.model_copy(
        update={
            "host_capability": binding.host_capability.model_copy(
                update={
                    "host_context": old,
                    "grant_digest": host_context_digest(old),
                    "grant_expires_at": old.expires_at,
                }
            )
        }
    )
    current = verified(broker, run="next-run").context
    assert task_access_response(app_for(binding), TASK, current) is None


def test_admission_rechecks_expiry_after_verified_grant_waits(broker):
    grant = verified(broker)
    expired = grant.context.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="expired"):
        binding_for(replace(grant, context=expired))


@pytest.mark.parametrize(
    "field,value",
    [("workspace_ref", "other"), ("origin", "https://other.test"), ("host_app_id", "other")],
)
def test_task_guard_preserves_stable_host_identity(broker, field, value):
    grant = verified(broker)
    denied = task_access_response(
        app_for(binding_for(grant)), TASK, grant.context.model_copy(update={field: value})
    )
    assert denied is not None and denied.status_code == 404


def test_shared_pure_fence_checks_requested_run_and_verified_issuer(broker):
    grant = verified(broker, run="request-run")
    binding = binding_for(grant)
    args = {"task_id": TASK, "now": datetime.now(UTC), "authority_issuer": grant.authority_issuer}
    assert (
        require_task_host_context(binding, grant.context, run_id="request-run", **args).resource_id
        == THREAD
    )
    with pytest.raises(ValueError, match="Run"):
        require_task_host_context(binding, grant.context, run_id="another-run", **args)
    args["authority_issuer"] = "https://other.test"
    with pytest.raises(ValueError, match="issuer"):
        require_task_host_context(binding, grant.context, run_id="request-run", **args)


def test_individual_request_checks_verified_issuer_not_just_same_context(broker):
    grant = verified(broker, run="fresh-read-run")
    app = app_for(binding_for(grant))
    response = tenant_scope_response(
        app,
        RouteRequest(
            "GET",
            f"/tasks/{TASK}/artifacts",
            host_context=grant.context,
            verified_host_grant=replace(grant, authority_issuer="https://foreign.test"),
        ),
    )
    assert response is not None and response.status_code == 404
    response = tenant_scope_response(
        app, RouteRequest("GET", f"/tasks/{TASK}/artifacts", host_context=grant.context)
    )
    assert response is not None and response.status_code == 403


@pytest.mark.parametrize("prefix", ["sessions", "approvals"])
def test_sibling_session_and_approval_require_root_task_thread(broker, prefix):
    grant = verified(broker)
    app = app_for(binding_for(grant))
    mapped = []
    child = "33333333-3333-4333-8333-333333333333"

    def lookup(session):
        mapped.append(str(session))
        return TASK

    app.stores.tasks = SimpleNamespace(task_id_for_session=lookup)
    good = RouteRequest(
        "GET", f"/{prefix}/{child}", host_context=grant.context, verified_host_grant=grant
    )
    assert tenant_scope_response(app, good) is None
    wrong = verified(broker, thread="wrong")
    bad = RouteRequest(
        "GET", f"/{prefix}/{child}", host_context=wrong.context, verified_host_grant=wrong
    )
    assert tenant_scope_response(app, bad).status_code == 404
    assert mapped == [child, child]
    app.stores.tasks = SimpleNamespace(task_id_for_session=lambda _: None)
    assert tenant_scope_response(app, good).status_code == 404


def test_internal_operator_and_local_legacy_path_remain_unchanged():
    assert task_access_response(app_for(None), TASK, None) is None
    local = SimpleNamespace(
        stores=SimpleNamespace(
            sessions=SimpleNamespace(get_session=lambda _: SimpleNamespace(namespace_id=None)),
        )
    )
    assert task_access_response(local, TASK, None) is None


def test_binding_for_another_task_cannot_authorize_target(broker):
    grant = verified(broker)
    denied = task_access_response(
        app_for(binding_for(grant, task="22222222-2222-4222-8222-222222222222")),
        TASK,
        grant.context,
    )
    assert denied is not None and denied.status_code == 404
