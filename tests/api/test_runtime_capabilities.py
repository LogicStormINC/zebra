from agent_security import SUPPORTED_NETWORK_PROFILES
from agent_storage.postgres.migrations import MIGRATIONS
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_api.host_auth import _required_scopes_for_request
from zebra_agent_api.http import HostGrantHttpRequest


def test_runtime_capabilities_match_task_network_profiles(tmp_path) -> None:
    response = RouteAdapter(create_app(tmp_path / "capabilities.sqlite")).handle(
        RouteRequest(method="GET", path="/capabilities/runtime")
    )

    assert response.status_code == 200
    assert response.body == {
        "contract_version": 1,
        "schema_version": MIGRATIONS[-1].version,
        "network_profiles": list(SUPPORTED_NETWORK_PROFILES),
        "client_surface_contract_version": 0,
        "client_surface_metadata_contract_version": 0,
        "client_state_admission_contract_version": 0,
        "client_surface_open_contract_version": 0,
    }
    assert "full-gateway" in response.body["network_profiles"]
    assert _required_scopes_for_request(
        HostGrantHttpRequest(
            method="GET", path="/capabilities/runtime", origin=None, authorization="Bearer grant"
        )
    ) == ()  # The Host authorizer applies its default agent.run scope.
