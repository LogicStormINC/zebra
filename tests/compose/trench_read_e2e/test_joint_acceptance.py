"""Protocol guard tests are not the fourteen real acceptance cases."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from support import ConfigError, HttpResult
from test_runner import isolated_config as isolated_config_fixture

isolated_config = isolated_config_fixture


def joint_resources(isolated_config, monkeypatch):
    config, rows, manifest = isolated_config
    scope = manifest["namespace_id"]
    for role, port in (("proxy", 19009), ("frontend", 19010)):
        row = {
            "Id": sha256(role.encode()).hexdigest(),
            "Name": f"/{scope}-{role}",
            "State": {"Running": True},
            "Config": {"Labels": {"zebra.e2e.scratch_id": "fixture01"}, "Env": []},
            "NetworkSettings": {
                "Networks": {
                    scope + "-network": {"IPAddress": "172.25.0.22", "Aliases": [f"{scope}-{role}"]}
                },
                "Ports": {
                    "2019/tcp" if role == "proxy" else "3000/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": str(port)}
                    ]
                },
            },
        }
        rows.append(row)
        manifest["containers"][role] = {"id": row["Id"]}
    for row in rows:
        row["Image"] = "sha256:" + sha256((row["Name"] + "image").encode()).hexdigest()
        row["HostConfig"] = {"Privileged": False, "NetworkMode": scope + "-network"}
        row["Mounts"] = []
    manifest.update(
        schema_version=2,
        frontend_url=config.bff_url,
        proxy_admin_url="http://127.0.0.1:19009/config/",
        frontend_build_id="build-qa",
    )
    trench = rows[0]
    trench["Config"]["Env"].append("TRENCH_AI_AUTH_SECRET=" + "q" * 40)
    # The native runtime must target the pinned proxy, not an unproved external alias.
    config = __import__("dataclasses").replace(
        config, runtime_tasks_url=f"https://{scope}-proxy:8445/tasks"
    )
    trench["Config"]["Env"] = [
        entry for entry in trench["Config"]["Env"] if not entry.startswith("ZEBRA_TASKS_URL=")
    ]
    trench["Config"]["Env"].append("ZEBRA_TASKS_URL=" + config.runtime_tasks_url)
    trench["Config"]["Env"].extend(
        [
            f"ZEBRA_AGUI_COMMAND_URL=https://{scope}-proxy:8445/agui/commands",
            f"ZEBRA_HOST_GRANT_EXCHANGE_URL=https://{scope}-proxy:8444/exchange",
        ]
    )
    rows[3]["Config"]["Env"].extend(
        [
            f"ZEBRA_GRANT_BROKER_TRENCH_ME_URL=https://{scope}-proxy:8443/api/trench-ai/me",
            f"ZEBRA_GRANT_BROKER_TRENCH_SOURCES_URL=https://{scope}-proxy:8443/api/trench-ai/sources",
        ]
    )
    for _role, spec in manifest["containers"].items():
        row = next(item for item in rows if item["Id"] == spec["id"])
        spec.update(
            image_id=row["Image"],
            config_sha256=sha256(
                json.dumps(row["Config"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    Path(config.isolation_manifest).write_text(json.dumps(manifest))
    monkeypatch.setattr(
        "support.subprocess.run",
        lambda argv, **_: SimpleNamespace(
            stdout="build-qa\n"
            if argv[1:3] == ["exec", manifest["containers"]["frontend"]["id"]]
            else json.dumps(rows)
        ),
    )

    def read(method, url, **kwargs):
        assert method == "GET"
        if url.endswith("/config/"):
            body = {
                "apps": {
                    "http": {
                        "servers": {
                            "host": {
                                "listen": [":8443"],
                                "upstreams": [
                                    {"dial": f"{scope}-trench_api:8000"},
                                    {"dial": f"{scope}-frontend:3000"},
                                ],
                            },
                            "broker": {
                                "listen": [":8444"],
                                "upstreams": [{"dial": f"{scope}-broker:8090"}],
                            },
                            "zebra": {
                                "listen": [":8445"],
                                "upstreams": [{"dial": f"{scope}-zebra_api:8000"}],
                            },
                        }
                    }
                }
            }
        elif url.endswith("/me"):
            body = {
                "code": 0,
                "data": {
                    "viewer": {"user_id": config.user_id, "workspace_id": config.workspace_id}
                },
            }
        else:
            body = {}
        return HttpResult(200, json.dumps(body).encode(), {})

    monkeypatch.setattr("support.request", read)
    return config, rows, manifest


def test_joint_preflight_is_readonly_and_pins_running_build(isolated_config, monkeypatch):
    from isolation import joint_preflight

    config, _, _ = joint_resources(isolated_config, monkeypatch)
    result = joint_preflight(config)
    assert result["frontend_build_id"] == "build-qa"
    assert result["scope"] == "read_only_scratch_preflight_not_live_acceptance"
    assert result["full_goal_passed"] is False


@pytest.mark.parametrize("defect", ["image", "socket", "upstream", "principal", "build"])
def test_joint_preflight_rejects_drift_before_any_post(isolated_config, monkeypatch, defect):
    from isolation import joint_preflight

    config, rows, manifest = joint_resources(isolated_config, monkeypatch)
    if defect == "image":
        rows[2]["Image"] = "sha256:" + "f" * 64
    elif defect == "socket":
        rows[2]["Mounts"] = [{"Type": "bind", "Source": "/var/run/docker.sock"}]
    elif defect == "upstream":
        monkeypatch.setattr(
            "support.request",
            lambda *_args, **_kw: HttpResult(
                200, b'{"upstreams":[{"dial":"host.docker.internal:8000"}]}', {}
            ),
        )
    elif defect == "principal":
        original = __import__("support").request
        monkeypatch.setattr(
            "support.request",
            lambda method, url, **kw: HttpResult(
                200, b'{"data":{"viewer":{"user_id":"foreign","workspace_id":"workspace-1"}}}', {}
            )
            if url.endswith("/me")
            else original(method, url, **kw),
        )
    else:
        manifest["frontend_build_id"] = "wrong-build"
        Path(config.isolation_manifest).write_text(json.dumps(manifest))
    with pytest.raises(ConfigError):
        joint_preflight(config)


def test_simple_answer_rejects_retrospective_or_fixture_evidence():
    from joint_acceptance import validate_simple_answer

    with pytest.raises(ValueError):
        validate_simple_answer({"scope": "fixture"}, "ZEBRA_QA_SIMPLE_abc")


def test_missing_joint_inputs_remain_blocked_without_launch(tmp_path, monkeypatch):
    from joint_acceptance import run_joint

    monkeypatch.setattr("joint_acceptance.subprocess.run", lambda *_a, **_k: pytest.fail("launch"))
    assert run_joint({}, tmp_path, preflight_only=True) == 2
    result = json.loads((tmp_path / "joint-result.json").read_text())
    assert result["status"] == "blocked" and result["full_goal_passed"] is False
    assert result["healthy_samples"] == 0 and len(result["remaining_cases"]) == 14


def test_stale_image_cannot_start_live_acceptance(tmp_path, monkeypatch):
    import joint_acceptance as joint

    monkeypatch.setattr(joint, "load_config", lambda *_: object())
    monkeypatch.setattr(joint, "joint_preflight", lambda _: {})
    monkeypatch.setattr(joint, "native_admission_gate", lambda _: None)
    monkeypatch.setattr(joint, "native_p0_catalog", lambda _: [])
    monkeypatch.setattr(
        joint, "native_source_identity", lambda _: {"worker": {"current_checkout_match": False}}
    )
    monkeypatch.setattr(joint.subprocess, "run", lambda *_a, **_k: pytest.fail("launch"))
    assert joint.run_joint({}, tmp_path) == 2
    result = json.loads((tmp_path / "joint-result.json").read_text())
    assert result["status"] == "blocked"
    assert result["reason"] == "joint_latest_source_not_verified"


def test_commit_probe_inputs_are_private_and_removed_after_browser_exit(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import joint_acceptance as joint

    config = SimpleNamespace(
        bff_url="https://localhost", session_cookie="qa=private", timeout_seconds=10
    )
    monkeypatch.setattr(joint, "load_config", lambda *_: config)
    monkeypatch.setattr(joint, "joint_preflight", lambda _: {})
    monkeypatch.setattr(joint, "native_admission_gate", lambda _: None)
    monkeypatch.setattr(joint, "native_p0_catalog", lambda _: [])
    monkeypatch.setattr(
        joint,
        "native_source_identity",
        lambda _: {
            role: {"current_checkout_match": True} for role in ("worker", "zebra_api", "broker")
        },
    )
    paths = []

    def browser(*_args, **kwargs):
        inputs = json.loads(kwargs["input"])
        path = Path(inputs["commit_inputs_path"])
        assert path.stat().st_mode & 0o077 == 0
        assert json.loads(path.read_text())["QA_SECRET"] == "private-marker"
        assert "private-marker" not in kwargs["input"]
        paths.append(path)
        return SimpleNamespace(returncode=1, stderr="REAL_SIMPLE_ANSWER=FAILED phase=launch")

    monkeypatch.setattr(joint.subprocess, "run", browser)
    assert (
        joint.run_joint(
            {"ZEBRA_E2E_COMMIT_VISIBILITY": "1", "QA_SECRET": "private-marker"}, tmp_path
        )
        == 2
    )
    assert len(paths) == 1 and not paths[0].exists()
    assert "private-marker" not in (tmp_path / "joint-result.json").read_text()
