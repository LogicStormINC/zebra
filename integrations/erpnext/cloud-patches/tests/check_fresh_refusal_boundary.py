"""Pinned native105 runtime, network-none: typed probe + real heartbeat boundary.

The complete original fresh checks run first. This check does not claim SQL proof.
"""
from check_fresh_authority import *
from zebra_agent_worker import execution_recovery
from zebra_agent_worker.execution_errors import WorkerExecutionError
from agent_core.domain.leases import LeaseFence, WorkerLease
from agent_storage.postgres import erp_fresh_disposition

os.environ["ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES"] = "erp.example.test"  # MockTransport only.

assert not issubclass(fresh.EarlyFreshRefusal, WorkerExecutionError)
for status, expected in [(401, fresh.EarlyFreshRefusal), (403, fresh.EarlyFreshRefusal),
                         (408, fresh.EarlyFreshUnavailable), (425, fresh.EarlyFreshUnavailable),
                         (429, fresh.EarlyFreshUnavailable), (500, fresh.EarlyFreshUnavailable),
                         (502, fresh.EarlyFreshUnavailable), (503, fresh.EarlyFreshUnavailable),
                         (504, fresh.EarlyFreshUnavailable), (501, ExecutionAuthorityResolutionError),
                         (505, ExecutionAuthorityResolutionError), (302, ExecutionAuthorityResolutionError)]:
    gate = fresh.FreshERPAuthority(BINDING, REGISTRY, CREDENTIAL, task_id=TASK,
        client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json={"error":"withheld"}))))
    try: fresh.require_early_authority(gate.probe(datetime.now(UTC)))
    except Exception as error: assert type(error) is expected, (status, type(error))
    else: raise AssertionError(status)

for external, expected in [(httpx.ReadTimeout('secret'), fresh.EarlyFreshUnavailable),
                           (httpx.ConnectError('secret'), fresh.EarlyFreshUnavailable),
                           (httpx.RemoteProtocolError('secret'), ExecutionAuthorityResolutionError),
                           (ValueError('secret'), ExecutionAuthorityResolutionError)]:
    def fail(request): raise external
    gate = fresh.FreshERPAuthority(BINDING, REGISTRY, CREDENTIAL, task_id=TASK,
        client=httpx.Client(transport=httpx.MockTransport(fail)))
    try: fresh.require_early_authority(gate.probe(datetime.now(UTC)))
    except Exception as error:
        assert type(error) is expected, type(error)
        assert 'secret' not in str(error)
    else: raise AssertionError(type(external))

# Typed local registry revocation/drift is a known refusal before any HTTP.
for bound, profile in [(None, PROFILE), (PROFILE_BINDING.model_copy(update={'active':False}), PROFILE),
                       (PROFILE_BINDING, None), (PROFILE_BINDING, PROFILE.model_copy(update={'base_uri':'https://other.example.test'}))]:
    registry=NS(resolve_binding=lambda *a:bound,get_profile=lambda *a:profile)
    gate=fresh.FreshERPAuthority(BINDING,registry,CREDENTIAL,task_id=TASK,
        client=httpx.Client(transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(AssertionError('HTTP after local revocation')))))
    try: fresh.require_early_authority(gate.probe(datetime.now(UTC)))
    except fresh.EarlyFreshRefusal as error: assert error.reason=='host_identity_drift'
    else: raise AssertionError('local registry revocation was not classified')

for failure in [fresh.EarlyFreshRefusal('probe_rejected'), fresh.EarlyFreshUnavailable('probe_timeout'),
                ValueError('internal-unclassified')]:
    now = datetime.now(UTC)
    lease = WorkerLease(session_id=SID, fence=LeaseFence(control_plane_epoch=uuid4(), fencing_token=1,
        owner_instance_id='check'), acquired_at=now, heartbeat_at=now, expires_at=now+timedelta(seconds=30))
    claimed = NS(lease=lease)
    calls=[]
    claim_service = NS(heartbeat_lease=lambda *a, **kw: lease,
                       release_lease=lambda owned: calls.append('release'))
    def forbidden(*a, **kw): raise AssertionError('private recovery or fake failure')
    service = NS(_claim_service=claim_service, _resume_service=NS(require_resumable=lambda *a, **kw: NS(claimed=claimed)),
        _recovery_service=NS(recover_session=forbidden), _projection_recorder_factory=NS(build=forbidden))
    def refuse(owned, decision):
        assert owned == lease and decision is failure and calls == []
        calls.append('seal')
    with patch.object(execution_recovery, 'execute_claimed_with_stale_retry', side_effect=failure), \
         patch.object(execution_recovery, 'recover_execution_progress', side_effect=forbidden), \
         patch.object(execution_recovery, 'finalize_worker_setup_failure', side_effect=forbidden):
        try: execution_recovery._execute_with_heartbeat(service, claimed, now, 30, refuse)
        except Exception as error: assert error is failure, type(error)
        else: raise AssertionError('missing refusal')
    assert calls == (['release'] if type(failure) is ValueError else ['seal','release']), calls
print('PASS fixed probe classification, real native heartbeat seal-before-release, zero private/fake failure; unclassified errors remain unsealed')
