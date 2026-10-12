"""A bounded commit carries its complete publication intent to one owner."""

from hashlib import sha256

from agent_core.application.coverage_executor import CoverageExecutor
from agent_core.domain.coverage_persistence import coverage_result_bytes

from tests.agent_core.test_coverage_executor import executor, setup_execution


def test_batch_publication_and_acceptance_enter_one_evidence_hook(tmp_path):
    env = setup_execution(tmp_path, bodies=(("risk",),) * 9)
    env.artifacts.store_payloads_immutable = lambda payloads: tuple(
        env.artifacts.store_payload_immutable(payload, artifact_id=identifier)
        for identifier, payload in payloads
    )
    run, intents = executor(env), []

    def accept(request, payloads, *, fence, batch):
        assert batch and fence == env.fence
        assert len(payloads) == len(request.results) + 1 == 10
        identifier, result = payloads[-1]
        assert request.result_artifact_ref == f"artifact://{identifier}"
        assert result.payload == coverage_result_bytes(request.results)
        assert request.result_artifact_digest == sha256(result.payload).hexdigest()
        assert all(payload.session_id == env.binding.session_id for _, payload in payloads)
        assert all(env.artifacts.get_payload(key) is None for key, _ in payloads)
        intents.append(request)
        return CoverageExecutor._commit_evidence(
            run, request, payloads, fence=fence, batch=batch,
        )

    run._commit_evidence = accept
    assert run.execute_batch(fence=env.fence, batch_commits=True) == (18, 18)
    assert len(intents) == 2
    assert len(env.store.receipts) == 2
