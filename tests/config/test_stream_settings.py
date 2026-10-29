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


def test_capacity_is_server_owned_off_and_strict_finite():
    from agent_core.domain.stream_admission import TransientCapacityPolicy

    assert load_stream_settings({}).capacity_policy is None
    policy = TransientCapacityPolicy()
    loaded = load_stream_settings({"ZEBRA_STREAM_CAPACITY_POLICY": policy.model_dump_json()})
    assert loaded.capacity_policy == policy
    for values in (
        {"run_slots": True},
        {"generation_bytes": 1.5},
        {"active_seconds": 3601},
        {"deployment_rows": 2**53},
        {"ended_seconds": 0},
        {"epoch": " bad "},
    ):
        with pytest.raises(ValueError):
            TransientCapacityPolicy.model_validate(values)


def test_native_interaction_revision_is_separately_disabled_by_default():
    assert not load_stream_settings({}).agui_native_interaction_enabled
    enabled = load_settings(env={"ZEBRA_AGUI_NATIVE_INTERACTION_ENABLED": "true"}).stream
    assert enabled.agui_native_interaction_enabled
    assert not enabled.agui_profiles_enabled
    with pytest.raises(ValueError):
        load_stream_settings({"ZEBRA_AGUI_NATIVE_INTERACTION_ENABLED": "yes"})
    with pytest.raises(ValueError):
        StreamSettings(agui_native_interaction_enabled=1)
