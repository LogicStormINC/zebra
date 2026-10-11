"""Scratch topology safety contracts; not real model/browser acceptance."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess

import pytest
from launch_scratch import refresh_zebra_images, validate_plan
from scratch_topology import HERE, prepare
from support import E2EError


@pytest.fixture
def rendered_plan(tmp_path, monkeypatch):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI needed for read-only graph rendering")
    monkeypatch.setattr("scratch_topology.tempfile.mkdtemp", lambda **_: str(tmp_path))
    monkeypatch.setattr("scratch_topology.image_id", lambda _: "sha256:" + "a" * 64)

    def tls(root, _scope):
        for name in ("ca-bundle.crt", "tls.crt", "tls.key", "broker.pem"):
            (root / name).write_text("protocol-test-only")
        return "protocol-test-not-browser-proof"

    monkeypatch.setattr("scratch_topology.make_tls", tls)
    _root, env = prepare()
    env.update(HOST_IMAGE="sha256:" + "b" * 64, FRONTEND_IMAGE="sha256:" + "c" * 64)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(HERE / "compose.scratch.yml"),
            "config",
            "--format",
            "json",
        ],
        env={**os.environ, **env, "DEEPSEEK_API_KEY": "protocol-only-not-provider"},
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout), env


def test_actual_rendered_graph_is_scoped_before_launch(rendered_plan):
    graph, env = rendered_plan
    validate_plan(graph, env)


@pytest.mark.parametrize("role", ["worker", "zebra_api", "migrate", "trench_api", "broker"])
def test_rendered_env_cannot_redirect_native_storage_or_authority(rendered_plan, role):
    graph, env = rendered_plan
    graph = copy.deepcopy(graph)
    key = {
        "trench_api": "DATABASE_URL",
        "broker": "ZEBRA_GRANT_BROKER_NAMESPACE_ID",
    }.get(role, "ZEBRA_DATABASE_URL")
    graph["services"][role]["environment"][key] = "application-resource"
    with pytest.raises(E2EError, match="scratch_compose_actual_route_invalid"):
        validate_plan(graph, env)


@pytest.mark.parametrize("defect", ["mount", "port", "privileged", "external", "unknown", "cap"])
def test_plan_rejects_unsafe_resources_before_writes(rendered_plan, defect):
    graph, env = rendered_plan
    graph = copy.deepcopy(graph)
    if defect == "mount":
        graph["services"]["worker"]["volumes"][0]["source"] = "/var/run/docker.sock"
    elif defect == "port":
        graph["services"]["worker"]["ports"] = [{"host_ip": "0.0.0.0"}]
    elif defect == "privileged":
        graph["services"]["worker"]["privileged"] = True
    elif defect == "external":
        graph["networks"]["scratch"]["external"] = True
    elif defect == "cap":
        graph["services"]["worker"]["cap_add"] = ["SYS_ADMIN"]
    else:
        graph["services"]["unowned"] = graph["services"]["worker"]
    with pytest.raises(E2EError):
        validate_plan(graph, env)


def test_refresh_exact_image_pins_waits_for_owned_graph_proof(tmp_path, monkeypatch):
    images = {
        role: "sha256:" + value * 64
        for role, value in (("api", "a"), ("worker", "b"), ("migrate", "c"))
    }
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps(images))
    (tmp_path / "runner-inputs.json").write_text(json.dumps({"TRENCH_E2E_BFF_URL": "scratch"}))
    env = {"SCRATCH_SCOPE": "zebra-progress-e2e-qa-123456789abc", "WORKER_IMAGE": "old"}
    monkeypatch.setattr("launch_scratch.image_id", lambda value: value)
    monkeypatch.setattr("support.load_config", lambda *_: object())

    def reject(_):
        raise E2EError("not_owned")

    monkeypatch.setattr("isolation.joint_preflight", reject)
    with pytest.raises(E2EError, match="not_owned"):
        refresh_zebra_images(tmp_path, env, pins)
    assert env["WORKER_IMAGE"] == "old" and "API_IMAGE" not in env
    monkeypatch.setattr("isolation.joint_preflight", lambda _: {})
    refresh_zebra_images(tmp_path, env, pins)
    assert env["WORKER_IMAGE"] == images["worker"]
    assert env["EVIDENCE_SUBDIR"] == "evidence-" + "b" * 12
    pins.write_text(json.dumps({**images, "frontend": "sha256:" + "d" * 64}))
    with pytest.raises(E2EError, match="scratch_image_pins_invalid"):
        refresh_zebra_images(tmp_path, env, pins)
