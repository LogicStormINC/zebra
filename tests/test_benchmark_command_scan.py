import pytest
from psycopg.conninfo import conninfo_to_dict

from scripts.benchmark_command_scan import checked_dsn


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres@localhost:12345/rabbitmq_baseline?hostaddr=203.0.113.1",
        "postgresql://postgres@localhost:12345/rabbitmq_baseline?service=production",
        "postgresql://postgres@203.0.113.1:12345/rabbitmq_baseline",
        "postgresql://postgres@localhost:12345/production",
        "postgresql://postgres@localhost/rabbitmq_baseline",
    ],
)
def test_rejects_target_overrides_without_connecting(dsn):
    with pytest.raises(ValueError):
        checked_dsn(dsn)


def test_pins_hostaddr_against_environment_override(monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.1")
    config = conninfo_to_dict(
        checked_dsn("postgresql://postgres@localhost:12345/rabbitmq_baseline")
    )
    assert config["host"] == config["hostaddr"] == "127.0.0.1"
    assert config["dbname"] == "rabbitmq_baseline"
    assert config["port"] == "12345"
