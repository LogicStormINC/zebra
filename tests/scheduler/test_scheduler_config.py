from __future__ import annotations

import pytest
from zebra_agent_scheduler.config import load_scheduler_settings


def environment() -> dict[str, str]:
    return {
        "ZEBRA_SCHEDULER_ID": "scheduler-a",
        "ZEBRA_SCHEDULER_GRANT_ISSUER": "https://broker.example",
        "ZEBRA_SCHEDULER_GRANT_AUDIENCE": "zebra",
        "ZEBRA_SCHEDULER_GRANT_JWKS_URI": "https://broker.example/.well-known/jwks.json",
        "ZEBRA_SCHEDULER_ALLOWED_ORIGINS": "https://trench.example",
        "ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL": "https://broker.example/exchange",
        "ZEBRA_SCHEDULER_WORKLOAD_IDENTITY": "scheduler",
        "ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET": "secret",
    }


def test_scheduler_settings_are_bounded_and_secret_free_in_repr() -> None:
    settings = load_scheduler_settings(environment())

    assert settings.claimant == "scheduler-a"
    assert settings.batch_size == 20
    assert settings.grant_exchange.verification.audience == "zebra"
    assert "secret" not in repr(settings)


def test_scheduler_settings_fail_before_process_start() -> None:
    values = environment()
    values["ZEBRA_SCHEDULER_BATCH_SIZE"] = "201"
    with pytest.raises(ValueError, match="between 1 and 200"):
        load_scheduler_settings(values)

    values = environment()
    values["ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL"] = "http://broker.example/exchange"
    with pytest.raises(ValueError, match="HTTPS"):
        load_scheduler_settings(values)
