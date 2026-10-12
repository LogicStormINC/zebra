import pytest
from zebra_agent_config import load_settings
from zebra_agent_config.stream_settings import StreamSettings, load_stream_settings


def test_default_off_and_typed_environment():
    assert load_stream_settings({}) == StreamSettings()
    assert load_settings(
        env={"ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED": "true"}
    ).stream.new_admission_enabled
    for value in ("yes", "enabled", "", "2"):
        with pytest.raises(ValueError):
            load_stream_settings({"ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED": value})
    with pytest.raises(ValueError):
        StreamSettings(new_admission_enabled=1)
