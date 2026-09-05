from dataclasses import replace

import pytest
from zebra_agent_config import load_settings
from zebra_agent_config.command_delivery import CommandDeliverySettings, load_command_delivery


def test_default_off_has_receipt_aware_fallback_and_no_credentials_in_repr():
    config = load_settings(env={}).command_delivery
    assert (
        not config.publish_enabled
        and not config.consume_enabled
        and config.scan_fallback_enabled
        and not config.scoped_rollout_enabled
    )
    configured = replace(config, relay_url="amqp://user:secret@localhost:5672/v")
    assert "secret" not in repr(configured)


@pytest.mark.parametrize(
    "values",
    [
        {"ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED": "false"},
        {"ZEBRA_COMMAND_SCOPED_ROLLOUT_ENABLED": "true"},
        {"ZEBRA_RABBIT_PUBLISH_ENABLED": "typo"},
        {"ZEBRA_RABBIT_CONSUME_ENABLED": "true"},
        {"ZEBRA_COMMAND_EXECUTION_SLOTS": "33"},
        {"ZEBRA_COMMAND_BATCH_SIZE": "0"},
        {"ZEBRA_COMMAND_TICK_SECONDS": "nan"},
    ],
)
def test_invalid_or_unrecoverable_configuration_rejected_safely(values):
    with pytest.raises(ValueError, match="configuration"):
        load_command_delivery(values)


def test_consume_without_command_publish_still_requires_diagnostic_publisher():
    values = {
        "ZEBRA_RABBIT_CONSUME_ENABLED": "true",
        "ZEBRA_RABBIT_CONSUMER_URL": "amqp://u:p@localhost:5672/v",
    }
    with pytest.raises(ValueError):
        load_command_delivery(values)
    config = load_command_delivery(
        {**values, "ZEBRA_RABBIT_RELAY_URL": values["ZEBRA_RABBIT_CONSUMER_URL"]}
    )
    assert config.consume_enabled and not config.publish_enabled


@pytest.mark.parametrize("kwargs", [{"execution_slots": True}, {"publish_enabled": 1}])
def test_direct_typed_settings_reject_bool_integer_confusion(kwargs):
    with pytest.raises(ValueError):
        CommandDeliverySettings(**kwargs)


@pytest.mark.parametrize(
    "shadow_url",
    [
        "amqp://consumer:p@localhost:5672/v",
        "amqp://consumer:other@broker.internal:5673/v?heartbeat=30",
        "amqp://cons%75mer:other@broker.internal:5673/v",
    ],
)
def test_scoped_rollout_requires_separate_shadow_credentials(shadow_url):
    common = {
        "publish_enabled": True,
        "consume_enabled": True,
        "scoped_rollout_enabled": True,
        "relay_url": "amqp://relay:p@localhost:5672/v",
        "consumer_url": "amqp://consumer:p@localhost:5672/v",
    }
    with pytest.raises(ValueError, match="separate credentials"):
        CommandDeliverySettings(
            **common,
            shadow_consumer_url=shadow_url,
        )


def test_scoped_rollout_rejects_percent_encoded_formal_principal():
    with pytest.raises(ValueError, match="separate credentials"):
        CommandDeliverySettings(
            publish_enabled=True,
            consume_enabled=True,
            scoped_rollout_enabled=True,
            relay_url="amqp://relay:p@localhost:5672/v",
            consumer_url="amqp://cons%75mer:p@localhost:5672/v",
            shadow_consumer_url="amqp://consumer:p@other:5673/v",
        )
