from pathlib import Path

SCRIPT = Path(__file__).with_name("run-smoke.sh")


def test_worker_health_requires_isolation_readiness_not_only_engine_version() -> None:
    compose = SCRIPT.parents[3] / "docker" / "compose.application.yml"
    worker = compose.read_text().split("  zebra-worker:", 1)[1].split("  zebra-scheduler:", 1)[0]
    health = worker.split("    healthcheck:", 1)[1]
    assert "zebra_agent_worker.runtime_preflight" in health
    assert "docker version" not in health
    assert "timeout: 30s" in health


def test_application_smoke_seeds_a_valid_host_registry_before_api_start() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    seed_index = source.index("HostRegistryRecord(")
    api_start_index = source.index(
        '"${APP_COMPOSE[@]}" up --detach --build --wait zebra-api'
    )

    assert seed_index < api_start_index
    assert "https://application-compose-test-authority.example" in source
    assert ".upsert_registry(" in source
    assert 'allowed_origins=("https://application-compose.example",)' in source
    assert '"RS256"' in source
    for required in (
        "ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL",
        "ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET",
        "ZEBRA_SCHEDULER_GRANT_ISSUER",
        "ZEBRA_SCHEDULER_GRANT_JWKS_URI",
        "ZEBRA_SCHEDULER_ALLOWED_ORIGINS",
    ):
        assert f"export {required}=" in source
