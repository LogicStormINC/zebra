"""The default deployment has no product-specific prerequisites."""

from pathlib import Path

import pytest
from zebra_agent_scheduler.config import load_scheduler_settings

ROOT = Path(__file__).parents[1]


def test_base_application_and_env_are_product_neutral():
    for name in ("compose.application.yml", ".env.application.example", "compose.local-gvisor.yml"):
        assert "trench" not in (ROOT / "docker" / name).read_text().lower()
    assert "trench-acceptance.env" not in (
        ROOT / "docker/local-gvisor/recreate-application.sh"
    ).read_text()


def test_optional_scheduler_fails_closed_without_authority():
    with pytest.raises(ValueError, match="scheduler requires ZEBRA_SCHEDULER_GRANT_ISSUER"):
        load_scheduler_settings({})


def test_existing_product_overlays_choose_compatibility_explicitly():
    product = (ROOT / "docker/compose.rabbitmq-product-e2e.yml").read_text()
    assert "ZEBRA_HOST_MANIFEST_BINDING_POLICY: legacy" in product
    assert "ZEBRA_GRANT_BROKER_AUTHORITY_MODE: trench_legacy" in product
    compatibility = (ROOT / "docker/compose.trench-compat.yml").read_text()
    assert compatibility.count("ZEBRA_HOST_MANIFEST_BINDING_POLICY: legacy") == 2
    assert "ZEBRA_SCHEDULER_GRANT_EXCHANGE_PROTOCOL: legacy" in compatibility
