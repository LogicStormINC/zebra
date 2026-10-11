import pytest
from zebra_agent_config import load_settings
from zebra_agent_config.coverage_settings import CoverageWorkSettings


def test_coverage_work_is_configurable_without_task_budget_changes():
    assert load_settings(env={}).coverage_work == CoverageWorkSettings()
    settings = load_settings(env={
        "ZEBRA_COVERAGE_WORK_UNITS": "8",
        "ZEBRA_COVERAGE_WORK_INPUT_BYTES": "1024",
        "ZEBRA_COVERAGE_WORK_MILLISECONDS": "1000",
    })
    assert settings.coverage_work == CoverageWorkSettings(8, 1024, 1000)


@pytest.mark.parametrize("key,value", [
    ("UNITS", "0"), ("UNITS", "1001"), ("UNITS", "1.0"),
    ("INPUT_BYTES", "33554433"), ("MILLISECONDS", "60001"),
])
def test_invalid_work_config_refuses(key, value):
    with pytest.raises(ValueError):
        load_settings(env={f"ZEBRA_COVERAGE_WORK_{key}": value})
