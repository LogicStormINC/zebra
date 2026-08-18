from __future__ import annotations

import pytest
from zebra_agent_config import load_settings


def test_local_profile_exposes_explicit_axes_and_keeps_lazy_sqlite_defaults() -> None:
    settings = load_settings(env={})

    assert settings.deployment == "local"
    assert settings.storage_authority == "sqlite"
    assert settings.runtime_isolation == "trusted-local"
    assert settings.database_url.endswith("sessions.sqlite")


def test_production_profile_requires_postgresql_and_gvisor() -> None:
    image = "zebra/runtime@sha256:" + "a" * 64
    settings = load_settings(
        {
            "ZEBRA_PROFILE": "production",
            "ZEBRA_DATABASE_URL": "postgresql://zebra:test@db/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": image,
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        }
    )

    assert settings.deployment == "cloud"
    assert settings.storage_authority == "postgresql"
    assert settings.runtime_isolation == "gvisor"
    assert settings.runtime.require_workspace_quota is True


@pytest.mark.parametrize(
    "env, message",
    [
        (
            {
                "ZEBRA_PROFILE": "cloud",
                "ZEBRA_DATABASE_URL": "postgresql://zebra:test@db/zebra",
            },
            "requires ZEBRA_RUNTIME_CLASS=gvisor",
        ),
        (
            {
                "ZEBRA_PROFILE": "production",
                "ZEBRA_RUNTIME_CLASS": "gvisor",
                "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "b" * 64,
                "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
            },
            "requires a PostgreSQL DSN",
        ),
    ],
)
def test_invalid_profile_axes_fail_closed(env: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_settings(env)
