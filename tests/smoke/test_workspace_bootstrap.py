from agent_context.compiler import compile_context
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.runtime import RuntimeExecutionRequest
from agent_runtime import LocalRuntime, LocalWorkspace
from agent_security.policy import policy_profile
from agent_storage import SQLiteEventStore, SQLiteLeaseStore, SQLiteProjectionStore
from agent_tools.gateway import ToolExecutor, ToolRegistry
from zebra_agent_api.app import create_app
from zebra_agent_worker import SessionClaimService, SessionRecoveryService, worker_banner


def test_workspace_packages_import() -> None:
    assert SessionStatus.CREATED.value == "created"
    assert compile_context() == "context-bootstrap"
    assert ToolRegistry is not None
    assert ToolExecutor is not None
    assert LocalWorkspace is not None
    assert policy_profile() == "local-bootstrap"
    assert SQLiteEventStore is not None
    assert SQLiteLeaseStore is not None
    assert SQLiteProjectionStore is not None
    assert create_app() == "api-bootstrap"
    assert SessionClaimService is not None
    assert SessionRecoveryService is not None
    assert worker_banner() == "worker-ready:created"


def test_runtime_port_shape() -> None:
    runtime = LocalRuntime()
    result = runtime.execute(RuntimeExecutionRequest(command=("echo", "ok")))

    assert result.succeeded is True
    assert result.exit_code == 0
    assert "ok" in result.stdout
