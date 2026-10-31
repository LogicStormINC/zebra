"""Run on pinned105 + overlay_imports; no database, real model or external network."""

from fresh_authority_fixtures import (
    BINDING,
    CONTEXT,
    NOW,
    NS,
    REGISTRY,
    RUN,
    SID,
    TASK,
    UTC,
    BoundHostExecutionAuthorityResolver,
    EventActor,
    EventType,
    ExecutionAuthorityResolutionRequest,
    Mock,
    ModuleType,
    OpenAICompatibleModelGateway,
    Path,
    ThreadPoolExecutor,
    ToolCall,
    WorkerToolGateway,
    ZoneInfo,
    datetime,
    fresh,
    guard,
    httpx,
    importlib,
    json,
    os,
    patch,
    refused,
    select_attempt_authority,
    sys,
    timedelta,
    uuid4,
)
from fresh_authority_fixtures import CREDENTIAL as CREDENTIAL
from fresh_authority_fixtures import PROFILE as PROFILE
from fresh_authority_fixtures import PROFILE_BINDING as PROFILE_BINDING
from fresh_authority_fixtures import (
    ExecutionAuthorityResolutionError as ExecutionAuthorityResolutionError,
)

with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
    for mode, reason in [
        ("timeout", "probe_timeout"),
        ("malformed", "probe_unavailable"),
        ("expand", "probe_expiry_invalid"),
        ("drift", "host_identity_drift"),
        ("expired", "probe_expired"),
    ]:
        gate, host, recorder = guard()
        host.mode = mode
        refused(lambda *, gate=gate: gate.check("test"))
        assert recorder.events[-1].reason_code.endswith(reason), recorder.events[-1]
    gate, host, recorder = guard()
    gate.check("first")
    assert host.calls[-1]["toolCallId"] and host.calls[-1]["idempotencyKey"]
    assert recorder.events[-1].expires_at <= CONTEXT.expires_at
    # Live cloud lease/JWT + revoked host -> no file, command, MCP, management/client or
    # model dispatch.
    for name in (
        "files.read",
        "files.list",
        "files.search",
        "files.publish",
        "command.run",
        "mcp.test",
        "skills.read",
        "extensions.list",
        "client.test",
        "erpnext.read",
    ):
        gate, host, recorder = guard()
        gate.check("first")
        host.mode = "revoke"
        local = NS(execute=Mock(), model_tools=())
        gateway = WorkerToolGateway(local=local, fresh_authority_check=gate.check)
        call = ToolCall(tool_call_id=uuid4(), name=name, arguments={}, created_at=NOW)
        result = gateway.execute(call)
        assert (
            result.status.value == "failed" and result.metadata["execution_state"] == "not_executed"
        )
        local.execute.assert_not_called()
        assert CONTEXT.expires_at > datetime.now(UTC) and recorder.active
        assert str(call.tool_call_id) in recorder.events[-1].reason_code
    gate, host, recorder = guard()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: gate.check("parallel", str(i)), range(24)))
    assert len(recorder.events) == 24 and len(host.calls) == 24
    # Selected Bound identity is preserved, including its native renewal method.
    gate, host, recorder = guard()
    resolver, scope, provider = select_attempt_authority(
        None, None, None, None, SID, binding=BINDING, fresh_checker=gate.probe
    )
    assert (
        isinstance(resolver, BoundHostExecutionAuthorityResolver)
        and resolver.fresh_checker == gate.probe
    )
    resolver.resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=SID, attempt_number=1, scope=scope, validated_at=NOW
        )
    )
    host.mode = "revoke"
    refused(
        lambda: resolver.resolve_for_attempt(
            ExecutionAuthorityResolutionRequest(
                session_id=SID, attempt_number=1, scope=scope, validated_at=NOW
            )
        )
    )
    # Provider internal retry shares its existing request ID; revocation blocks the SECOND
    # HTTP attempt.
    gate, host, recorder = guard()
    sent = []

    def model_request(request):
        sent.append(request)
        host.mode = "revoke"
        return httpx.Response(
            503, json={"error": {"message": "test retry", "type": "server_error"}}
        )

    model = OpenAICompatibleModelGateway(
        provider_name="openai",
        base_url="https://model.example.test/v1",
        api_key="test-only",
        model_name="test-only",
        client=httpx.Client(transport=httpx.MockTransport(model_request)),
        max_retries=1,
    )
    gate.model(model)
    refused(lambda: model.complete([]))
    assert len(sent) == 1
    assert len(recorder.events) == 2
    ids = [x.reason_code.split(":")[2] for x in recorder.events]
    assert ids[0] == ids[1]
    gate, host, recorder = guard()
    host.mode = "revoke"
    sent.clear()
    gate.model(model)
    refused(lambda: model.complete_stream([], on_text_delta=lambda delta: None))
    assert sent == []
    # Disabled defaults and startup failure for incomplete/cross-namespace composition.
    with patch.dict(os.environ, {"ZEBRA_ERPNEXT_FRESH_AUTHORITY": "disabled"}):
        assert not fresh.enabled("erpnext")
    with patch.dict(os.environ, {"ZEBRA_ERPNEXT_FRESH_AUTHORITY": "enabled"}):
        for namespace in ("trench", None):
            try:
                fresh.enabled(namespace)
            except ValueError:
                pass
            else:
                raise AssertionError("namespace accepted")
        try:
            fresh.validate_wiring(
                "erpnext", None, REGISTRY, NS(host_tool_shared_secret="test-only")
            )
        except ValueError:
            pass
        else:
            raise AssertionError("missing loader accepted")

# Source seams are asserted separately from behavioral contracts; no fabricated E2E claim.
root = Path(__file__).resolve().parents[1]
source = (root / "overrides/apps/worker/src/zebra_agent_worker/execution_attempt.py").read_text()
assert (
    source.index("self._erp_workspace_containment.require")
    < source.index("FreshERPAuthority.for_execution")
    < source.index("worker_progress = finish_preparation")
    < source.index("inputs = prepare_execution_inputs")
)
assert "fresh_authority=fresh" in source
assert "local_tool_gateway.fresh_authority_check = fresh.check" in source
assert "erp_fresh_coverage_not_activated" in source
for name in ("openai_compatible", "deepseek_responses"):
    text = (
        root / f"overrides/packages/agent-integrations/src/agent_integrations/{name}.py"
    ).read_text()
    assert text.count("self.authority_check(call_id)") == 2
    assert text.count("if self.authority_check is not None:") >= 2
assert (
    "sink = checked_sink"
    in (root / "overrides/apps/worker/src/zebra_agent_worker/progress_recovery.py").read_text()
)
assert (
    'fresh_authority_check("transient_start", call_id)'
    in (root / "overrides/apps/worker/src/zebra_agent_worker/execution_context.py").read_text()
)
text = (root / "overrides/apps/worker/src/zebra_agent_worker/cloud_memory_recovery.py").read_text()
assert text.index('getattr(recovery, "fresh_maintenance_blocked"') < text.index("pending_reader =")
print(
    "PASS native Host HMAC, typed fresh denials, all-tool entry refus"
    "al, model retry/stream refusal, parallel journal, expiry clamp a"
    "nd source wiring"
)

# Durable and repair publication both use the same checked sink, before any canonical output.
HarnessEventDraft = __import__(
    "agent_core.harness.models", fromlist=("HarnessEventDraft",)
).HarnessEventDraft
cloud_memory_recovery = __import__(
    "zebra_agent_worker", fromlist=("cloud_memory_recovery",)
).cloud_memory_recovery
execution = __import__("zebra_agent_worker", fromlist=("execution",)).execution
progress_recovery = __import__(
    "zebra_agent_worker", fromlist=("progress_recovery",)
).progress_recovery

with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
    gate, host, recorder = guard()
    host.mode = "revoke"
    published = []
    progress = progress_recovery.WorkerProgressRecovery(
        NS(),
        NS(state=NS(pending_commentary=None, terminal=False, attempt_number=1)),
        lambda: None,
        8,
        fresh_authority_check=gate.check,
    )
    draft = HarnessEventDraft(
        EventType.PUBLIC_OUTPUT,
        EventActor.HARNESS,
        {"output_id": "output-existing", "phase": "answer", "attempt_number": 1},
    )
    with patch.object(progress_recovery, "repair_commentary", lambda *a: None):
        sink = progress.persist_with(published.append)
        refused(lambda: sink(draft))
    assert not published
    gate, host, recorder = guard()
    host.mode = "revoke"
    progress.fresh_authority_check = gate.check
    progress.head.state.pending_commentary = object()
    with patch.object(progress_recovery, "repair_commentary", lambda recovery, sink: sink(draft)):
        refused(lambda: progress.persist_with(published.append))
    assert not published
    # Denied early source cannot reach progress/attachment input recovery.
    fake_gate = NS(
        probe=lambda now: fresh.FreshDecision(
            fresh.ExecutionAuthorityDecision.DENIED, None, "test_revoked"
        )
    )
    claimed = NS(lease=NS(session_id=SID), recovery=NS(workspace=NS()))
    service = NS(_erp_fresh_enabled=True, _erp_workspace_containment=NS(require=Mock()))
    with (
        patch.object(execution, "recover_committed_completion", return_value=None),
        patch.object(fresh.FreshERPAuthority, "for_execution", return_value=fake_gate),
        patch.object(execution, "recover_execution_progress") as recover,
    ):
        refused(
            lambda: execution.SessionExecutionService._execute_claimed_session_once(
                service, claimed, started_at=NOW, ownership_check=lambda: None
            )
        )
        recover.assert_not_called()
    projection = NS(list_memory_recovery_sessions=Mock())
    cloud_memory_recovery.recover_completed_cloud_memory(
        worker_id="check",
        batch_size=1,
        lease_ttl_seconds=10,
        recovery=NS(fresh_maintenance_blocked=True),
        projection_store=projection,
    )
    projection.list_memory_recovery_sessions.assert_not_called()
print(
    "PASS early no-input boundary, durable/repair publication refusal"
    " and maintenance pre-query skip"
)

# Load the real Host callback + native cloud.owned with a strict Frappe boundary double.

frappe = ModuleType("frappe")
utils = ModuleType("frappe.utils")
package = ModuleType("zebra_erpnext")
package.__path__ = []
frappe.PermissionError = type("PermissionError", (ValueError,), {})
frappe.ValidationError = type("ValidationError", (ValueError,), {})
frappe.session = NS(user="Guest")
frappe.flags = NS(zebra_tool_call=False)
local_now = NOW.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
record = NS(
    user="qa-user",
    company="QA Company",
    conversation="conversation",
    run_id=RUN,
    workspace_ref=CONTEXT.workspace_ref,
    expires_at=local_now + timedelta(minutes=5),
)
conversation = NS(
    name="conversation",
    user="qa-user",
    company="QA Company",
    task_id=TASK,
    host_thread="host-thread",
    active_run_id=RUN,
    workspace_ref=CONTEXT.workspace_ref,
    status="running",
)
state = {"enabled": 1, "company": True, "paused": False}


def throw(message, *args):
    raise frappe.PermissionError(message)


frappe.throw = throw
frappe.set_user = lambda user: setattr(frappe.session, "user", user)
frappe.whitelist = lambda **kwargs: lambda fn: fn
frappe.as_json = lambda value: json.dumps(value, default=str)
frappe.db = NS(
    get_value=lambda doctype, *args, **kwargs: record
    if doctype == "Zebra Grant"
    else state["enabled"]
)


def permission(kind):
    assert kind == "read" and frappe.session.user == "qa-user"
    if not state["company"]:
        throw("Company read removed")


frappe.get_doc = (
    lambda doctype, name, *, for_update=False: conversation
    if doctype == "Zebra Conversation"
    else NS(check_permission=permission)
)
utils.get_datetime = (
    lambda value: datetime.fromisoformat(value) if isinstance(value, str) else value
)
utils.now_datetime = lambda: local_now
utils.get_system_timezone = lambda: "Asia/Shanghai"
frappe.utils = utils
frappe.conf = {
    "zebra_agent": dict(
        enabled=True,
        base_url="https://cloud.test",
        issuer="https://erp.example.test",
        origin="https://erp.example.test",
        signing_key="unused",
        ca_file="unused",
        host_secret="test-only-hmac",
    )
}
responses = ModuleType("werkzeug.wrappers")
responses.Response = object


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


with patch.dict(
    sys.modules,
    {
        "frappe": frappe,
        "frappe.utils": utils,
        "zebra_erpnext": package,
        "werkzeug.wrappers": responses,
        "requests": ModuleType("requests"),
    },
):
    cloud = load("zebra_erpnext.cloud", root / "host-baseline/zebra_erpnext/cloud.py")
    package.cloud = cloud
    authority = load("zebra_erpnext.authority", root / "host-overrides/zebra_erpnext/authority.py")
    gateway = load("zebra_erpnext.gateway", root / "host-overrides/zebra_erpnext/gateway.py")
    gateway.raw = lambda value: value
    gate, host, recorder = guard()
    # Real native HostToolGateway generated the body/headers; use it unchanged at Frappe's boundary.
    requests = []

    def capture(request):
        requests.append(request)
        return host(request)

    gate.client = httpx.Client(transport=httpx.MockTransport(capture))
    with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
        gate.probe(NOW).require_allowed()
    native = requests[-1]
    frappe.local = NS(
        request=NS(
            method="POST",
            headers=native.headers,
            get_json=lambda **kwargs: json.loads(native.content),
        )
    )
    result = json.loads(gateway.invoke()["output"])
    # Shanghai 8-hour offset: 5-minute local Grant clamps the 10-minute UTC context.
    assert datetime.fromisoformat(result["expires_at"]) == NOW + timedelta(minutes=5)
    assert frappe.session.user == "Guest" and not frappe.flags.zebra_tool_call
    for change in (
        "disabled",
        "company",
        "owner",
        "company_drift",
        "workspace",
        "task",
        "thread",
        "run",
        "deleted",
        "cancelled",
        "paused",
        "naive",
    ):
        before = vars(conversation).copy()
        original_record = vars(record).copy()
        original_json = frappe.local.request.get_json
        if change == "disabled":
            state["enabled"] = 0
        elif change == "company":
            state["company"] = False
        elif change == "owner":
            conversation.user = "someone-else"
        elif change == "company_drift":
            conversation.company = "Different Company"
        elif change == "workspace":
            conversation.workspace_ref = "different"
        elif change == "task":
            conversation.task_id = "different"
        elif change == "thread":
            conversation.host_thread = "different"
        elif change == "run":
            conversation.active_run_id = "different"
        elif change in ("deleted", "cancelled"):
            conversation.status = change
        elif change == "paused":
            frappe.conf["zebra_agent"]["admission_paused"] = True
        elif change == "naive":
            args = dict(gate.arguments, expires_at=local_now.isoformat())
            frappe.session.user = "qa-user"
            try:
                authority.check(record, args)
            except frappe.PermissionError:
                pass
            else:
                raise AssertionError("naive frozen expiry accepted")
            frappe.session.user = "Guest"
            continue
        try:
            gateway.invoke()
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Host accepted " + change)
        assert frappe.session.user == "Guest"
        vars(conversation).update(before)
        vars(record).update(original_record)
        state.update(enabled=1, company=True)
        frappe.conf["zebra_agent"].pop("admission_paused", None)
        frappe.local.request.get_json = original_json
    # Bad signature must fail before user delegation.
    frappe.local.request.headers = dict(native.headers) | {"X-Zebra-Host-Auth": "bad"}
    try:
        gateway.invoke()
    except frappe.PermissionError:
        pass
    else:
        raise AssertionError("invalid signature accepted")
    assert frappe.session.user == "Guest"
print(
    "PASS real Host HMAC/delegated/owned callback with disabled-user,"
    " Company removal, owner/task/thread/run drift, pause/cancel and "
    "Asia/Shanghai clamp mocks"
)


native_execution = __import__("fresh_authority_native_execution")
check_dispatch_and_context = native_execution.check_dispatch_and_context
check_continuation_startup = native_execution.check_continuation_startup
check_stored_binding = __import__("fresh_authority_stored_binding").check_stored_binding

SessionStatus = check_dispatch_and_context(execution)
check_stored_binding(execution, SessionStatus)
check_continuation_startup(execution, SessionStatus)
