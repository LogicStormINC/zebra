from pathlib import Path

SCRIPT = Path(__file__).with_name("run-smoke.sh")


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
