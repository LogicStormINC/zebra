from pathlib import Path

RUNNER = Path(__file__).with_name("run_default_e2e.py")
VERIFY = Path(__file__).with_name("verify_durable.py")
SEED = Path(__file__).with_name("seed_session.py")
STUB = Path(__file__).with_name("stub_model.py")
COMPOSE = Path(__file__).with_name("compose.yml")


def test_runner_executes_composition_scenarios_in_order() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    infrastructure = source.index('"infrastructure"')
    acceptance = source.index('"session_acceptance"')
    fail_closed = source.index('"worker_fail_closed"')
    handoff = source.index('"handoff_effect_read"')

    assert infrastructure < acceptance < fail_closed < handoff


def test_runner_keeps_execution_tier_fail_closed() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert "gvisor_available" in source
    assert '"runsc"' in source
    assert "ZEBRA_EFFECT_E2E_ENABLE_EXECUTION_TIER" in source
    assert "ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED" in source
    # The runner must never report PASS while execution tier scenarios are skipped.
    assert "self.failures == 0 and execution_enabled" in source


def test_worker_fail_closed_asserts_zero_side_effects() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert '"effect_outbox_rows"] == 0' in source
    assert 'status_first["status"] == "ready"' in source
    assert "_find_sqlite" in source
    assert "OCI engine does not advertise runtime runsc" in source
    assert "workspace quota requires the workspace root to be a dedicated mount point" in source


def test_durable_verifier_uses_only_authoritative_postgres_paths() -> None:
    source = VERIFY.read_text(encoding="utf-8")

    assert "postgres_control_plane_stores" in source
    assert "bootstrap_control_plane_epoch" in source
    assert ".terminal_keys(" in source
    assert ".has_uncertain(" in source
    assert "sqlite" not in source.lower()


def test_seed_drives_the_committed_api_application_object() -> None:
    source = SEED.read_text(encoding="utf-8")

    assert "from zebra_agent_api import create_app" in source
    assert "RouteAdapter" in source
    assert '"execute": False' in source


def test_stub_stays_provider_shaped_and_prompt_gated() -> None:
    source = STUB.read_text(encoding="utf-8")

    assert "text/event-stream" in source
    assert '"tool_calls"' in source
    assert '"finish_reason": "tool_calls"' in source
    assert 'command_tool = next(' in source
    assert '"name": command_tool' in source

    compose_source = COMPOSE.read_text(encoding="utf-8")
    assert "postgres:17.5-alpine3.21" in compose_source
    assert "25497:5432" in compose_source
    assert "25496:9000" in compose_source
