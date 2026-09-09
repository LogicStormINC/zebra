from zebra_agent_config import load_settings


def test_cloud_extension_worker_defaults_off_and_requires_explicit_opt_in(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings(env={}).cloud_extension_worker_enabled is False
    assert (
        load_settings(
            env={"ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED": "true"}
        ).cloud_extension_worker_enabled
        is True
    )


def test_cloud_skill_worker_defaults_off_and_requires_explicit_opt_in(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_settings(env={}).cloud_skill_worker_enabled is False
    assert load_settings(
        env={"ZEBRA_CLOUD_SKILL_WORKER_ENABLED": "true"}
    ).cloud_skill_worker_enabled is True
