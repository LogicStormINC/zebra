"""Assertion scenarios for fresh authority native execution."""

from fresh_authority_fixtures import (
    BINDING,
    NOW,
    NS,
    SID,
    UTC,
    EventActor,
    EventType,
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityRevalidation,
    Mock,
    Path,
    Recorder,
    SessionEvent,
    ToolCall,
    WorkerToolGateway,
    ast,
    datetime,
    fresh,
    guard,
    httpx,
    inspect,
    os,
    patch,
    refused,
    uuid4,
)


def check_dispatch_and_context(execution):
    # The native outer fence checks before scheduling/payloads; actual dispatch retains uncertainty
    # semantics.
    FencedEffectToolGateway = __import__(
        "agent_tools.effect_guard", fromlist=("FencedEffectToolGateway",)
    ).FencedEffectToolGateway
    effect_identity = __import__(
        "agent_tools.effect_guard_support", fromlist=("effect_identity",)
    ).effect_identity

    with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
        gate, host, recorder = guard()
        host.mode = "revoke"
        effect = FencedEffectToolGateway.__new__(FencedEffectToolGateway)
        effect._ownership_check = lambda: None
        effect._fresh_authority_check = gate.check
        effect._gateway = NS(execute=Mock())
        effect._schedule = Mock()
        call = ToolCall(
            tool_call_id=uuid4(),
            name="command.run",
            arguments={"command": "unused"},
            created_at=NOW,
        )
        identity = effect_identity(call, "unchanged-authority")
        refused(lambda: effect.execute(call))
        effect._schedule.assert_not_called()
        effect._gateway.execute.assert_not_called()
        assert effect_identity(call, "unchanged-authority") == identity
        gate, host, recorder = guard()
        host.mode = "revoke"
        effect._fresh_authority_check = gate.check
        effect._mutation_guard = recorder.mutation
        effect._execution_started = Mock()
        effect._dispatch = NS(
            fail_no_effect=Mock(return_value="terminal"),
            mark_uncertain=Mock(return_value="uncertain"),
        )
        effect._terminal_event = Mock(return_value="event")
        effect._accept_event = Mock()
        claim = NS(dispatch=NS(dispatch_id=uuid4()))
        refused(lambda: effect._execute_claim(claim, call))
        effect._dispatch.fail_no_effect.assert_called_once()
        effect._dispatch.mark_uncertain.assert_not_called()
        effect._gateway.execute.assert_not_called()
        effect._execution_started.assert_not_called()
        # After dispatch starts the unchanged native catch keeps uncertainty; it never retries
        # business work.
        effect._fresh_authority_check = None
        effect._gateway.execute = Mock(side_effect=RuntimeError("uncertain test"))
        try:
            effect._execute_claim(claim, call)
        except RuntimeError:
            pass
        else:
            raise AssertionError("uncertain effect swallowed")
        effect._dispatch.mark_uncertain.assert_called_once()
        effect._gateway.execute.assert_called_once_with(call)
    print(
        "PASS native fenced outer admission, failed-no-effect before disp"
        "atch and unchanged uncertain-effect handling"
    )

    # SPEC regression 1: actual shared execution entry blocks completion payloads in READY/RUNNING.
    ExecutionAuthoritySnapshot = __import__(
        "agent_core.domain.execution_authority", fromlist=("ExecutionAuthoritySnapshot",)
    ).ExecutionAuthoritySnapshot
    SessionStatus = __import__(
        "agent_core.domain.sessions", fromlist=("SessionStatus",)
    ).SessionStatus
    _completion_recovery = __import__(
        "zebra_agent_worker", fromlist=("completion_recovery",)
    ).completion_recovery
    context_materialization = __import__(
        "zebra_agent_worker", fromlist=("context_materialization",)
    ).context_materialization

    for status in (SessionStatus.READY, SessionStatus.RUNNING):
        for committed in (False, True):
            payloads = (
                [
                    NS(
                        event_type=EventType.ANSWER_COMMITTED,
                        payload={"assistant_message": "private"},
                    )
                ]
                if committed
                else []
            )
            completion_reader = Mock(return_value=payloads)
            factory = NS(
                completion_reader=completion_reader,
                build=Mock(return_value=NS(worker_mutation_authority="lease-valid")),
            )
            service = NS(
                _erp_fresh_enabled=True,
                _erp_workspace_containment=None,
                _projection_recorder_factory=factory,
            )
            claimed = NS(
                lease=NS(session_id=SID), recovery=NS(session=NS(status=status), workspace=NS())
            )
            fake_gate = NS(
                probe=lambda now: fresh.FreshDecision(
                    fresh.ExecutionAuthorityDecision.REVOKED, None, "test_revoked"
                )
            )
            with (
                patch.object(fresh.FreshERPAuthority, "for_execution", return_value=fake_gate),
                patch.object(execution, "recover_execution_progress") as progress,
            ):
                refused(
                    lambda *,
                    claimed=claimed,
                    execute=execution.SessionExecutionService._execute_claimed_session_once,
                    service=service: execute(
                        service, claimed, started_at=NOW, ownership_check=lambda: None
                    )
                )
            completion_reader.assert_not_called()
            factory.build.assert_not_called()
            progress.assert_not_called()
    # Disabled mode preserves native completion first, without loading fresh Task bindings.
    with (
        patch.object(
            execution, "recover_committed_completion", return_value="already-committed"
        ) as recover,
        patch.object(fresh.FreshERPAuthority, "for_execution") as create,
    ):
        service = NS(_erp_fresh_enabled=False)
        assert (
            execution.SessionExecutionService._execute_claimed_session_once(
                service, claimed, started_at=NOW, ownership_check=lambda: None
            )
            == "already-committed"
        )
        create.assert_not_called()
        recover.assert_called_once()

    # SPEC regression 2: outer fresh succeeds, inner fresh rejects; native result is exactly
    # failed_no_effect.
    with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
        gate, host, recorder = guard()
        local = NS(execute=Mock())

        def check_boundary(boundary, identity):
            if boundary.startswith("tool:"):
                host.mode = "revoke"
            gate.check(boundary, identity)

        inner = WorkerToolGateway(local=local, fresh_authority_check=check_boundary)
        effect = FencedEffectToolGateway.__new__(FencedEffectToolGateway)
        effect._ownership_check = lambda: None
        effect._fresh_authority_check = check_boundary
        effect._gateway = inner
        effect._mutation_guard = recorder.mutation
        effect._execution_started = Mock()
        effect._effect_payloads = None
        effect._dispatch = NS(
            fail_no_effect=Mock(return_value="no-effect"), mark_uncertain=Mock(), complete=Mock()
        )
        effect._terminal_event = Mock(return_value="terminal")
        effect._accept_event = Mock()
        call = ToolCall(
            tool_call_id=uuid4(),
            name="command.run",
            arguments={"command": "never-run"},
            created_at=NOW,
        )
        identity = effect_identity(call, "same-authority")
        claim = NS(dispatch=NS(dispatch_id=uuid4()))
        result = effect._execute_claim(claim, call)
        assert (
            result.tool_call_id == call.tool_call_id
            and result.metadata["execution_state"] == "not_executed"
        )
        assert effect_identity(call, "same-authority") == identity
        effect._dispatch.fail_no_effect.assert_called_once()
        effect._dispatch.mark_uncertain.assert_not_called()
        effect._dispatch.complete.assert_not_called()
        local.execute.assert_not_called()
        assert [x.reason_code.split(":")[1] for x in recorder.events] == ["effect_dispatch", "tool"]
        assert gate._denied
        refused(lambda: gate.check("model", "unchanged-provider-id"))
        local.execute.assert_not_called()

    # SPEC regression 3: real prepare_worker_context + AttemptAuthorityEvidence.persist + Bound
    # resolver.
    class ContextRecorder(Recorder):
        def __init__(self):
            super().__init__(None)
            self.canonical = []
            self.session = NS(session_id=SID, current_sequence=0)
            self._ownership_check = lambda: None
            self.worker_mutation_authority = None

        def append(self, kind, actor, payload, **kwargs):
            with self.lock:
                if kind is EventType.EXECUTION_AUTHORITY_RESOLVED:
                    assert self.snapshot is None
                    self.snapshot = ExecutionAuthoritySnapshot.model_validate(payload)
                else:
                    super().append(kind, actor, payload)
                self.session.current_sequence += 1
                self.canonical.append(
                    SessionEvent.create(
                        session_id=SID,
                        sequence=self.session.current_sequence,
                        event_type=kind,
                        actor=actor,
                        payload=payload,
                        created_at=datetime.now(UTC),
                    )
                )

    with patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}):
        for revoked in (True, False):
            gate, host, _ = guard()
            journal = ContextRecorder()
            seen = []

            def callback(request, *, host=host, revoked=revoked):
                result = host(request)
                if revoked and len(host.calls) == 2:
                    host.mode = "revoke"  # after selected resolver's initial allow
                return result

            gate.client = httpx.Client(transport=httpx.MockTransport(callback))
            claimed = NS(
                lease=NS(session_id=SID),
                recovery=NS(session=journal.session, workspace=NS(workspace_root=Path("/unused"))),
            )

            def recover_session(*args, claimed=claimed, journal=journal, seen=seen, **kwargs):
                seen.append(journal.session.current_sequence)
                return NS(
                    session=NS(session_id=SID, current_sequence=journal.session.current_sequence),
                    workspace=claimed.recovery.workspace,
                )

            def read_inputs(*args, journal=journal):
                return list(journal.canonical)

            materialize = Mock(return_value=None)
            with (
                patch.object(context_materialization, "recover_turn_extension", return_value=None),
                patch.object(context_materialization, "materialize_worker_context", materialize),
            ):

                def prepare(*, claimed=claimed, gate=gate, journal=journal):
                    return context_materialization.prepare_worker_context(
                        store=NS(),
                        task_binding_loader=lambda sid: BINDING,
                        resolver=None,
                        static_scope=None,
                        scope_provider=None,
                        recovery_service=NS(recover_session=recover_session),
                        event_store=NS(),
                        recorder=journal,
                        claimed=claimed,
                        events=[],
                        task=NS(),
                        active_capsule_id=None,
                        as_of=NOW,
                        ownership_check=lambda: None,
                        fresh_authority=gate,
                        execution_input_reader=read_inputs,
                    )

                if revoked:
                    refused(prepare)
                else:
                    prepared = prepare()
            assert len(journal.canonical) == 2
            initial = ExecutionAuthoritySnapshot.model_validate(journal.canonical[0].payload)
            checked = ExecutionAuthorityRevalidation.model_validate(journal.canonical[1].payload)
            assert checked.prior_snapshot_digest == initial.snapshot_digest
            assert checked.reason_code.startswith("erp_fresh:context_materialization:")
            if revoked:
                materialize.assert_not_called()
                assert checked.decision.value == "denied"
                assert seen == [1]
            else:
                materialize.assert_called_once()
                assert checked.decision.value == "narrowed"
                assert seen == [1, 2]
                assert materialize.call_args.kwargs["session"].current_sequence == 2
                assert materialize.call_args.kwargs["events"] == journal.canonical
                assert (
                    prepared.claimed.recovery.session.current_sequence == 2
                    and prepared.events == journal.canonical
                )
    print(
        "PASS SPEC regressions: completion-before-payload guard, inner re"
        "jection/no-effect, post-persist context journal and refreshed re"
        "visions"
    )

    # Only the entry fresh check is converted; authority errors from an already-started handler stay
    # uncertain.
    local = NS(
        execute=Mock(side_effect=ExecutionAuthorityResolutionError("started handler failure"))
    )
    inner = WorkerToolGateway(local=local, fresh_authority_check=lambda *args: None)
    effect._gateway = inner
    effect._fresh_authority_check = None
    effect._dispatch.mark_uncertain.reset_mock()
    effect._dispatch.fail_no_effect.reset_mock()
    refused(lambda: effect._execute_claim(claim, call))
    local.execute.assert_called_once_with(call)
    effect._dispatch.mark_uncertain.assert_called_once()
    effect._dispatch.fail_no_effect.assert_not_called()
    print("PASS started-handler authority exception preserves native uncertain result")
    return SessionStatus


def check_continuation_startup(execution, SessionStatus):
    # QUALITY: execute the shared startup block and all native direct-event constructors.
    LeaseFence = __import__("agent_core.domain.leases", fromlist=("LeaseFence",)).LeaseFence
    Session = __import__("agent_core.domain.sessions", fromlist=("Session",)).Session
    WorkspaceProjection = __import__(
        "agent_core.domain.workspaces", fromlist=("WorkspaceProjection",)
    ).WorkspaceProjection
    WorkspaceStatus = __import__(
        "agent_core.domain.workspaces", fromlist=("WorkspaceStatus",)
    ).WorkspaceStatus
    WorkerMutationAuthority = __import__(
        "agent_core.ports.aggregate_mutation", fromlist=("WorkerMutationAuthority",)
    ).WorkerMutationAuthority
    execution_continuations = __import__(
        "zebra_agent_worker", fromlist=("execution_continuations",)
    ).execution_continuations
    ClaimedSession = __import__(
        "zebra_agent_worker.claims", fromlist=("ClaimedSession",)
    ).ClaimedSession
    DurableHarnessEventRecorder = __import__(
        "zebra_agent_worker.execution_events", fromlist=("DurableHarnessEventRecorder",)
    ).DurableHarnessEventRecorder
    RecoveredSession = __import__(
        "zebra_agent_worker.recovery", fromlist=("RecoveredSession",)
    ).RecoveredSession

    startup_node = next(
        node
        for node in ast.walk(ast.parse(inspect.getsource(execution.execute_claimed_session_once)))
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and item.context_expr.args
            and isinstance(item.context_expr.args[0], ast.Constant)
            and item.context_expr.args[0].value == "continuation start lost a sequence race"
            for item in node.items
        )
    )
    startup_code = compile(
        ast.Module(body=[startup_node], type_ignores=[]), "<shared-continuation-start>", "exec"
    )
    for kind in ("approved", "completed", "clarification", "child_wakeup", "client_effect"):
        for concurrent in (False, True):
            gate, host, prior = guard()
            primary = NS(
                session=Session(
                    session_id=SID,
                    title="test",
                    status=SessionStatus.READY,
                    created_at=NOW,
                    updated_at=NOW,
                    current_sequence=1,
                ),
                workspace=WorkspaceProjection(
                    session_id=SID,
                    workspace_root="/unused",
                    prepared_at=NOW,
                    updated_at=NOW,
                    current_sequence=1,
                    status=WorkspaceStatus.PREPARED,
                ),
            )
            accepted = []
            cas_rejections = []
            fence = LeaseFence(
                control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="test-worker"
            )

            def commit(
                event,
                session,
                workspace,
                *,
                authority,
                accepted=accepted,
                cas_rejections=cas_rejections,
                primary=primary,
            ):
                if authority.expected_stream_revision != primary.session.current_sequence:
                    cas_rejections.append(event)
                    raise ValueError("test independent primary CAS conflict")
                assert event.sequence == primary.session.current_sequence + 1
                primary.session, primary.workspace = session, workspace
                accepted.append(event)
                return NS(event=event, session=session, workspace=workspace)

            recorder = DurableHarnessEventRecorder(
                session=primary.session,
                workspace=primary.workspace,
                event_store=NS(read_since=lambda *args: []),
                projection_store=NS(get_session=lambda sid, *, primary=primary: primary.session),
                workspace_store=NS(),
                model_call_indexer=Mock(),
                tool_run_indexer=Mock(),
                worker_projection_transaction=NS(commit_worker_event=commit),
                worker_mutation_authority=WorkerMutationAuthority(
                    deployment_namespace="erpnext",
                    session_id=SID,
                    expected_stream_revision=1,
                    lease_fence=fence,
                ),
            )

            def recover(*args, primary=primary, **kwargs):
                return RecoveredSession(
                    primary.session,
                    primary.workspace,
                    primary.session.current_sequence + 1,
                    primary.session.current_sequence,
                    False,
                )

            recovery = NS(recover_session=Mock(side_effect=recover))
            claimed = ClaimedSession(recover(), NS(session_id=SID, fence=fence))
            initial = SessionEvent.create(
                session_id=SID,
                sequence=1,
                event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
                actor=EventActor.SYSTEM,
                payload=prior.snapshot.to_event_payload(),
                created_at=NOW,
            )
            gate.bind_recorder(lambda *, recorder=recorder: recorder, [initial])
            with patch.dict(
                os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "erp.example.test"}
            ):
                gate.check("extension_materialization")
                gate.check("context_injection")
            assert (
                recorder.session.current_sequence == 3
                and claimed.recovery.session.current_sequence == 1
            )
            call = ToolCall(tool_call_id=uuid4(), name="command.run", arguments={}, created_at=NOW)
            continuation = NS(
                tool_call=call,
                completed_output="done" if kind == "completed" else None,
                metadata={},
                effect_id=str(uuid4()),
            )
            selected = execution_continuations.ActiveContinuations(
                approved=continuation if kind in ("approved", "completed") else None,
                clarification=continuation if kind == "clarification" else None,
                child_wakeup=continuation if kind == "child_wakeup" else None,
                client_effect=continuation if kind == "client_effect" else None,
            )

            def select(*args, concurrent=concurrent, primary=primary, selected=selected, **kwargs):
                if concurrent:  # independent writer wins after refresh, before first direct append
                    primary.session = primary.session.model_copy(update={"current_sequence": 4})
                    primary.workspace = primary.workspace.model_copy(update={"current_sequence": 4})
                return selected

            scope = dict(
                execution.execute_claimed_session_once.__globals__,
                fresh=gate,
                authority_recorder=recorder,
                claimed=claimed,
                self=NS(_recovery_service=recovery, _delegation_store=None, _projection_store=None),
                ownership_check=lambda: None,
                session_events=[initial],
                execution_events=NS(),
                started_at=NOW,
                release_gateway=lambda: None,
                attempt_number=2,
            )
            with patch.object(
                execution_continuations, "recover_active_continuations", side_effect=select
            ):
                if concurrent:
                    try:
                        exec(startup_code, scope)
                    except ValueError as error:
                        assert "CAS conflict" in str(error)
                    else:
                        raise AssertionError("concurrent primary advance ignored")
                    assert len(cas_rejections) == 1 and len(accepted) == 2
                    assert recorder.session.current_sequence == 3
                else:
                    exec(startup_code, scope)
                    assert scope["continuations"] is selected
                    starts = accepted[2:]
                    assert [event.sequence for event in starts] == (
                        [4, 5] if kind == "approved" else [4]
                    )
                    identity = starts[-1].payload.get(
                        "tool_call_id", starts[-1].payload.get("clarification_id")
                    )
                    assert identity == str(call.tool_call_id)
                    if kind == "client_effect":
                        assert starts[0].payload["client_effect_id"] == continuation.effect_id
                    assert scope["claimed"].lease is claimed.lease
                    assert scope["claimed"].recovery.session.current_sequence == starts[-1].sequence
                    assert (
                        scope["claimed"].recovery.workspace.current_sequence == starts[-1].sequence
                    )
                    # Refresh reused the recorder's committed Cloud projection;
                    # recovery is only the native post-start read.
                    recovery.recover_session.assert_called_once()
    print(
        "PASS shared continuation startup: fresh journal -> native refres"
        "h -> all five native start branches; stable IDs and independent "
        "CAS conflict refusal"
    )
