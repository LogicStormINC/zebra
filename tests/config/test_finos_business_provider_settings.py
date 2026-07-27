from __future__ import annotations

import pytest
from zebra_agent_config import load_settings


def test_load_settings_reads_fixed_finos_business_provider_endpoint() -> None:
    settings = load_settings(
        {
            "ZEBRA_FINOS_JOURNAL_PROVIDER_BASE_URL": "http://finos.internal/",
            "ZEBRA_FINOS_JOURNAL_PROVIDER_TIMEOUT_SECONDS": "3.5",
        }
    )

    assert settings.finos_journal_provider.base_url == "http://finos.internal"
    assert settings.finos_journal_provider.timeout_seconds == 3.5


@pytest.mark.parametrize(
    "values",
    [
        {"ZEBRA_FINOS_JOURNAL_PROVIDER_BASE_URL": "ftp://finos.internal"},
        {"ZEBRA_FINOS_JOURNAL_PROVIDER_TIMEOUT_SECONDS": "0"},
    ],
)
def test_load_settings_rejects_invalid_finos_business_provider_configuration(
    values: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        load_settings(values)
