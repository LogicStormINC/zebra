"""Explicit shared standard projector/state binding, default off, exactly six queues."""

import sqlite3
from dataclasses import replace

import pytest
from agent_integrations.ag_ui.standard_profiles import standard_profiles
from agent_integrations.ag_ui.standard_state import StandardProjectionState
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api.factory import _agui_profiles
from zebra_agent_config.stream_settings import StreamSettings, load_stream_settings
from zebra_agent_worker.ag_ui_composition import configure_agui_projection_work

from tests.worker.test_loop import _settings


def test_profiles_require_explicit_settings_and_bind_the_same_six_versions(tmp_path):
    settings = _settings(tmp_path / "profile-composition.sqlite")
    stores = sqlite_control_plane_stores(tmp_path / "profile-composition.sqlite")
    assert _agui_profiles(settings) is None
    legacy = configure_agui_projection_work(stores, settings, None, None)
    assert legacy is not None and len(legacy.consumers) == 2
    enabled = replace(settings, stream=replace(settings.stream, agui_profiles_enabled=True))
    registry = _agui_profiles(enabled)
    assert registry.available_profiles == tuple(sorted(p.profile_id for p in standard_profiles()))
    service = configure_agui_projection_work(stores, enabled, None, None)
    assert service is not None and len(service.consumers) == 6
    versions = [consumer.work._version for consumer in service.consumers]
    assert len(set(versions)) == 6
    assert versions[:2] == ["ag-ui-v1", "ag-ui-v1-coverage"]
    for consumer in service.consumers[2:]:
        api_profile = registry.select(consumer.profile.profile_id)
        assert type(api_profile.projector) is type(consumer.profile.projector)
        assert api_profile.state_type is consumer.profile.state_type is StandardProjectionState
    # Construction binds ports only; process startup owns enabling queues.
    with sqlite3.connect(tmp_path / "profile-composition.sqlite") as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM task_projection_work_projectors").fetchone()[0]
            == 0
        )
    for consumer in service.consumers:
        consumer.work.enable_projection_work()
    with sqlite3.connect(tmp_path / "profile-composition.sqlite") as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT projector_version FROM task_projection_work_projectors WHERE enabled=1"
            )
        } == set(versions)
    with pytest.raises(ValueError):
        stores.projection_work_for_version("extra-projector").enable_projection_work()


def test_new_flag_is_strict_and_preserves_old_positional_settings():
    assert not load_stream_settings({}).agui_profiles_enabled
    assert StreamSettings(True).new_admission_enabled
    assert not StreamSettings(True).agui_profiles_enabled
    assert load_stream_settings(
        {"ZEBRA_AGUI_STANDARD_PROFILES_ENABLED": "true"}
    ).agui_profiles_enabled
    for value in ("yes", "", "2"):
        with pytest.raises(ValueError):
            load_stream_settings({"ZEBRA_AGUI_STANDARD_PROFILES_ENABLED": value})
    with pytest.raises(ValueError):
        StreamSettings(agui_profiles_enabled=1)
