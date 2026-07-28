from agent_integrations.mem0.circuit import Mem0CircuitBreaker


def test_half_open_circuit_allows_only_one_probe() -> None:
    now = [10.0]
    circuit = Mem0CircuitBreaker(
        failure_threshold=1,
        recovery_seconds=5,
        clock=lambda: now[0],
    )
    circuit.record_failure()

    assert circuit.allows_request() is False
    now[0] += 5
    assert circuit.allows_request() is True
    assert circuit.allows_request() is False

    circuit.record_success()
    assert circuit.allows_request() is True
