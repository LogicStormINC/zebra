from agent_context.compiler import compile_context
from agent_core.domain.sessions import SessionStatus
from agent_runtime.adapters.local import LocalRuntime
from agent_security.policy import policy_profile
from agent_tools.gateway import gateway_name
from zebra_agent_api.app import create_app
from zebra_agent_worker.main import worker_banner


def test_workspace_packages_import() -> None:
    assert SessionStatus.CREATED.value == "created"
    assert compile_context() == "context-bootstrap"
    assert gateway_name() == "tool-gateway-bootstrap"
    assert policy_profile() == "local-bootstrap"
    assert create_app() == "api-bootstrap"
    assert worker_banner() == "worker-ready:created"


def test_runtime_port_shape() -> None:
    runtime = LocalRuntime()
    assert runtime.execute(["echo", "ok"]) == 0
    assert runtime.execute([]) == 1
