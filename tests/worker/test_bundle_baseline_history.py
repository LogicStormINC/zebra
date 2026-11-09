"""Published default baselines survive recovery without rewriting frozen facts."""

from dataclasses import replace

import pytest
from agent_core.application.workspace_projection import rebuild_workspace
from agent_storage import LocalArtifactPayloadReader, SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_config import ApiSettings
from zebra_agent_config.bundle_settings import baseline_digest
from zebra_agent_worker.bundle_assembly import require_task_compatibility
from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError
from zebra_agent_worker.task_recovery import recover_task

from tests.test_bundle_assembly import settings, write_catalog
from tests.worker.test_bundle_execution import seed

PUBLISHED = "sha256:c7748ed8d32a5c534d4c7c8290fd71f5d5d3c01d46c3d38c53665a5cce900fdc"
INTERMEDIATE = "sha256:1bcba9cf83df0210d435af0775a9e97a5bea57ecf993f502cdf53c92e84cd73f"


def test_disabled_agui_defaults_keep_published_digest_and_enabled_flags_stay_pinned():
    original = settings()
    assert baseline_digest(original, "ab" * 32) == PUBLISHED
    for field in ("agui_profiles_enabled", "agui_native_interaction_enabled"):
        enabled = replace(original, stream=replace(original.stream, **{field: True}))
        assert baseline_digest(enabled, "ab" * 32) not in (PUBLISHED, INTERMEDIATE)


@pytest.mark.parametrize("digest", [PUBLISHED, INTERMEDIATE])
def test_actual_frozen_task_accepts_exact_history_and_rejects_configuration_drift(
    tmp_path, monkeypatch, digest
):
    with monkeypatch.context() as fixture:
        fixture.setattr("tests.test_bundle_assembly.baseline_digest", lambda *args: digest)
        assembly, configured, _ = write_catalog(tmp_path, settings())
    sid, _ = seed(tmp_path, assembly)
    store = SQLiteEventStore(tmp_path / "worker.db")
    events = store.list_for_session(sid)
    before = [event.model_dump_json() for event in events]
    task = recover_task(
        events,
        workspace=rebuild_workspace(events),
        fallback_title="fallback",
        attachment_reader=LocalArtifactPayloadReader(
            SQLiteArtifactPayloadStore(tmp_path / "read.db")
        ),
    )
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "fixture-only")
    require_task_compatibility(configured, task)
    assert task.definition_snapshot.bound_version.runtime_assembly == assembly
    for mutated in (
        replace(configured, api=ApiSettings(auth_token="changed")),
        replace(configured, stream=replace(configured.stream, agui_profiles_enabled=True)),
        replace(
            configured, stream=replace(configured.stream, agui_native_interaction_enabled=True)
        ),
        replace(
            configured,
            host_execution_authority=replace(configured.host_execution_authority, enabled=True),
        ),
    ):
        with pytest.raises(RetryableWorkerSetupError, match="INCOMPATIBLE_RUNTIME_BUNDLE"):
            require_task_compatibility(mutated, task)
    assert [event.model_dump_json() for event in store.list_for_session(sid)] == before
