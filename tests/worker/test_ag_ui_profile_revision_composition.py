"""All version enable combinations compose identical API and Worker bindings."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from zebra_agent_api.api_status_mixin import ApiStatusMixin
from zebra_agent_api.factory import _agui_profiles
from zebra_agent_config.stream_settings import StreamSettings
from zebra_agent_worker.ag_ui_composition import configure_agui_projection_work

from tests.worker.execution.worker_execution_support import _settings


@pytest.mark.parametrize(
    "base,interactions", [(False, False), (False, True), (True, False), (True, True)]
)
def test_revision_composition_and_discovery_are_explicit(base, interactions, tmp_path, monkeypatch):
    settings = replace(
        _settings(tmp_path / "unused.sqlite"),
        stream=StreamSettings(
            agui_profiles_enabled=base, agui_native_interaction_enabled=interactions
        ),
    )
    registry = _agui_profiles(settings)
    versions = []
    stores = SimpleNamespace(
        tasks=object(),
        projection_work=object(),
        coverage_projection_work=None,
        projection_work_for_version=lambda version: versions.append(version) or object(),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.ag_ui_composition.AgUiCheckpointConsumer",
        lambda tasks, work, **kwargs: SimpleNamespace(work=work, profile=kwargs["profile"]),
    )
    service = configure_agui_projection_work(stores, settings, "fixture", None)
    workers = {
        (p.profile_id, p.revision, type(p.projector), p.state_type)
        for consumer in service.consumers
        if (p := consumer.profile) is not None
    }
    api = (
        set()
        if registry is None
        else {
            (p.profile_id, p.revision, type(p.projector), p.state_type)
            for name, revisions in registry.available_revisions.items()
            for revision in revisions
            if (p := registry.select(name, str(revision))) is not None
        }
    )
    assert workers == api
    assert len(versions) == (8 if base and interactions else 4 if base else 0)
    app = SimpleNamespace(settings=settings, client_platform=None, agui_profiles=registry)
    metadata = ApiStatusMixin.get_runtime_capabilities(app).body.get("metadata", {})
    if not base:
        assert not metadata
    else:
        expected = (1, 2) if interactions else (1,)
        if interactions:
            assert metadata["aguiProfileRevisions"] == {
                name: list(expected) for name in registry.available_profiles
            }
        else:
            assert "aguiProfileRevisions" not in metadata
        assert metadata["aguiProfiles"] == list(registry.available_profiles)
        assert all(registry.select(name).revision == 1 for name in registry.available_profiles)
