"""Prepare, run and stop only a freshly generated independent joint QA project."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scratch_seed import seed_authority, seed_identity, seed_storage
from scratch_topology import (
    HERE,
    ROLES,
    TRENCH,
    docker,
    image_id,
    inspect_owned,
    pin_manifest,
    prepare,
    private_json,
    provider_inputs,
)
from support import E2EError, request

SDK_NAMES = ("contracts", "ui-contracts", "client-core", "react", "react-charts")


def validate_plan(document: dict[str, Any], environment: dict[str, str]) -> None:
    scope = environment["SCRATCH_SCOPE"]
    if not re.fullmatch(r"zebra-progress-e2e-qa-[a-f0-9]{12}", scope) or document["name"] != scope:
        raise E2EError("scratch_compose_scope_invalid")
    if set(document["services"]) != {*ROLES, "migrate"}:
        raise E2EError("scratch_compose_roles_invalid")
    expected = {
        role: {
            "ZEBRA_DATABASE_URL": environment["ZEBRA_DATABASE_URL"],
            "ZEBRA_DEPLOYMENT_NAMESPACE": scope,
            "ZEBRA_S3_ENDPOINT": f"http://{scope}-object-store:9000",
            "ZEBRA_LIVE_REDIS_URL": f"redis://{scope}-redis:6379/1",
        }
        for role in ("zebra_api", "worker", "migrate")
    }
    expected["trench_api"] = {
        "DATABASE_URL": environment["TRENCH_DATABASE_URL"],
        "POSTGRES_HOST": scope + "-postgres",
        "POSTGRES_DB": scope + "_trench",
        "REDIS_HOST": scope + "-redis",
        "ZEBRA_TASKS_URL": f"https://{scope}-proxy:8445/tasks",
        "ZEBRA_CLIENT_NAMESPACE_ID": scope,
        "ZEBRA_HOST_GRANT_EXCHANGE_URL": f"https://{scope}-proxy:8444/exchange",
    }
    expected["broker"] = {
        "ZEBRA_GRANT_BROKER_NAMESPACE_ID": scope,
        "ZEBRA_GRANT_BROKER_ISSUER": environment["BROKER_ORIGIN"],
        "ZEBRA_GRANT_BROKER_TRENCH_ME_URL": f"https://{scope}-proxy:8443/api/trench-ai/me",
    }
    for role, service in document["services"].items():
        if (
            service["container_name"] != scope + "-" + role
            or service["labels"].get("zebra.e2e.scratch_id") != environment["SCRATCH_ID"]
            or service.get("privileged")
            or service.get("network_mode") == "host"
            or service.get("restart") != "no"
            or service.get("build")
        ):
            raise E2EError("scratch_compose_target_invalid")
        if any(port.get("host_ip") != "127.0.0.1" for port in service.get("ports", [])):
            raise E2EError("scratch_compose_port_invalid")
        if (
            service.get("cap_drop") != ["ALL"]
            or service.get("security_opt") != ["no-new-privileges:true"]
            or service.get("cap_add", []) != (["NET_BIND_SERVICE"] if role == "proxy" else [])
        ):
            raise E2EError("scratch_compose_capabilities_invalid")
        if set(service["networks"]) != {"scratch"}:
            raise E2EError("scratch_compose_network_invalid")
        if any(
            service.get("environment", {}).get(k) != v for k, v in expected.get(role, {}).items()
        ):
            raise E2EError("scratch_compose_actual_route_invalid")
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                source = Path(mount["source"]).resolve()
                root = Path(environment["SECRET_ROOT"]).resolve()
                if (
                    not source.is_relative_to(root)
                    or not source.is_file()
                    or not mount["read_only"]
                ):
                    raise E2EError("scratch_compose_mount_invalid")
            elif mount["type"] != "volume" or mount["source"] not in {
                "pg",
                "objects",
                "redis_data",
            }:
                raise E2EError("scratch_compose_volume_invalid")
    for key, suffix in (("ZEBRA_DATABASE_URL", "zebra"), ("TRENCH_DATABASE_URL", "trench")):
        if not environment[key].endswith(f"@{scope}-postgres:5432/{scope}_{suffix}"):
            raise E2EError("scratch_compose_database_invalid")
    if any(
        key != "scratch" or value.get("external") or value["name"] != scope + "-network"
        for key, value in document.get("networks", {}).items()
    ):
        raise E2EError("scratch_compose_network_invalid")
    for key, spec in document.get("volumes", {}).items():
        suffix = {"pg": "pg", "objects": "objects", "redis_data": "redis-data"}[key]
        if spec.get("external") or spec["name"] != scope + "-" + suffix:
            raise E2EError("scratch_compose_volume_invalid")


def compose(environment: dict[str, str], arguments: list[str], timeout: int = 120) -> str:
    values = {**os.environ, **environment, **provider_inputs()}
    prefix = ["compose", "--project-directory", str(HERE), "-f", str(HERE / "compose.scratch.yml")]
    graph = json.loads(docker([*prefix, "config", "--format", "json"], environment=values))
    validate_plan(graph, environment)
    return docker([*prefix, *arguments], environment=values, timeout=timeout)


def build_base(environment: dict[str, str], role: str, reference: str) -> str:
    frozen = image_id(reference)
    tag = environment["SCRATCH_SCOPE"] + "-base-" + role
    docker(["tag", frozen, tag])
    if image_id(tag) != frozen:
        raise E2EError("scratch_build_base_drift")
    return tag


def build_host(environment: dict[str, str]) -> None:
    base = build_base(environment, "host", "trench-backend:local")
    name = environment["SCRATCH_SCOPE"] + "-host"
    docker(
        [
            "build",
            "--platform",
            docker(["image", "inspect", base, "--format", "{{.Os}}/{{.Architecture}}"]).strip(),
            "-f",
            str(HERE / "Dockerfile.host"),
            "--build-arg",
            "BASE_IMAGE=" + base,
            "-t",
            name,
            str(TRENCH),
        ],
        timeout=600,
    )
    environment["HOST_IMAGE"] = image_id(name)


def build_frontend(root: Path, environment: dict[str, str]) -> str:
    base = build_base(environment, "frontend", "trench-frontend:local")
    scope = environment["SCRATCH_SCOPE"]
    # Probe only package paths, never app Env/settings. This one-off has no network/data mounts.
    code = (
        "const {createRequire}=require('module');const path=require('path');"
        "const req=createRequire('/app/frontend/package.json');"
        "const nested=createRequire(req.resolve('@zebra-agent/react'));"
        "console.log(JSON.stringify(Object.fromEntries("
        + json.dumps(list(SDK_NAMES))
        + ".map(n=>[n,path.resolve(path.dirname((n==='contracts'?nested:req)"
        ".resolve('@zebra-agent/'+n)),'..')]))))"
    )
    locations = json.loads(
        docker(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--name",
                scope + "-probe",
                "--label",
                "zebra.e2e.scratch_id=" + environment["SCRATCH_ID"],
                "--entrypoint",
                "node",
                base,
                "-e",
                code,
            ]
        )
    )
    import tempfile

    context = Path(tempfile.mkdtemp(prefix="frontend-build-", dir=root))
    frontend = TRENCH / "toc-frontend"
    local_locations = json.loads(
        subprocess.check_output(
            ["node", "-e", code.replace("/app/frontend", str(frontend))], text=True, timeout=30
        )
    )
    # Build cache is not runtime output; excluding it avoids transferring ~2GiB of webpack cache.
    shutil.copytree(frontend / ".next", context / ".next", ignore=shutil.ignore_patterns("cache"))
    shutil.copytree(frontend / "public", context / "public")
    for name, target in locations.items():
        relative = Path(target).relative_to("/app/frontend/node_modules/.pnpm")
        source = Path(local_locations[name])
        shutil.copytree(source, context / "sdk" / relative, symlinks=True)
    name = scope + "-frontend"
    docker(
        [
            "build",
            "--platform",
            docker(["image", "inspect", base, "--format", "{{.Os}}/{{.Architecture}}"]).strip(),
            "-f",
            str(HERE / "Dockerfile.frontend"),
            "--build-arg",
            "BASE_IMAGE=" + base,
            "-t",
            name,
            str(context),
        ],
        timeout=300,
    )
    environment["FRONTEND_IMAGE"] = image_id(name)
    return (frontend / ".next" / "BUILD_ID").read_text().strip()


def ready(url: str, timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = request("GET", url, timeout=2)
            if response.status == 200:
                return
        except E2EError:
            pass
        time.sleep(0.25)
    raise E2EError("scratch_http_not_ready")


def stop_owned(root: Path) -> None:
    state = json.loads((root / "state.json").read_text())
    environment = state["environment"]
    ids = list(state.get("containers", {}).values())
    if not ids:
        return
    rows = inspect_owned(environment, ids)
    # Exact recorded IDs; no globs, shared networks, app daemon commands or volume deletion.
    for row in rows:
        docker(["stop", "--time", "5", row["Id"]], timeout=15)


def record_containers(root: Path, environment: dict[str, str], roles: tuple[str, ...]) -> None:
    state = json.loads((root / "state.json").read_text())
    rows = inspect_owned(environment, [environment["SCRATCH_SCOPE"] + "-" + role for role in roles])
    ids = {
        **state.get("containers", {}),
        **{r: row["Id"] for r, row in zip(roles, rows, strict=True)},
    }
    private_json(root / "state.json", {**state, "environment": environment, "containers": ids})


def refresh_zebra_images(root: Path, environment: dict[str, str], pins: Path) -> None:
    """Authorize the existing owned graph before replacing its three exact image pins."""
    from isolation import joint_preflight
    from run_acceptance import REQUIRED_ENV
    from support import load_config

    if pins.stat().st_size > 4096:
        raise E2EError("scratch_image_pins_invalid")
    images = json.loads(pins.read_text())
    if set(images) != {"api", "worker", "migrate"} or any(
        not isinstance(value, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", value)
        for value in images.values()
    ):
        raise E2EError("scratch_image_pins_invalid")
    resolved = {role.upper() + "_IMAGE": image_id(value) for role, value in images.items()}
    if any(resolved[role.upper() + "_IMAGE"] != value for role, value in images.items()):
        raise E2EError("scratch_image_pin_drift")
    inputs = json.loads((root / "runner-inputs.json").read_text())
    inputs.setdefault("TRENCH_E2E_BUSINESS_SNAPSHOT_URL", inputs["TRENCH_E2E_BFF_URL"])
    inputs.setdefault("ZEBRA_E2E_WORKER_RESTART_URL", inputs["TRENCH_E2E_BFF_URL"])
    inputs.setdefault("TRENCH_E2E_EVENT_ID", "unused_in_simple_answer")
    os.environ["SSL_CERT_FILE"] = str(root / environment["SCRATCH_SCOPE"] / "ca-bundle.crt")
    joint_preflight(load_config(inputs, REQUIRED_ENV))
    environment.update(resolved)
    environment["EVIDENCE_SUBDIR"] = "evidence-" + images["worker"][7:19]


def start(root: Path, environment: dict[str, str], *, keep: bool) -> int:
    state = json.loads((root / "state.json").read_text())
    stage = "build"
    try:
        print("SCRATCH_STAGE=BUILD", flush=True)
        if "HOST_IMAGE" not in environment:
            build_host(environment)
            private_json(root / "state.json", {**state, "environment": environment})
        if "FRONTEND_IMAGE" not in environment:
            environment["FRONTEND_BUILD_ID"] = build_frontend(root, environment)
        build_id = environment["FRONTEND_BUILD_ID"]
        private_json(root / "state.json", {**state, "environment": environment})
        stage = "dependencies"
        # A new generated project cannot adopt pre-existing containers or volumes.
        existing = docker(
            [
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                "label=com.docker.compose.project=" + environment["SCRATCH_SCOPE"],
            ]
        )
        existing_ids = set(existing.split())
        if existing_ids != set(state.get("containers", {}).values()):
            raise E2EError("scratch_project_already_exists")
        for kind in ("network", "volume"):
            names = docker([kind, "ls", "--format", "{{.Name}}"])
            if not existing_ids and any(
                n.startswith(environment["SCRATCH_SCOPE"] + "-") for n in names.split()
            ):
                raise E2EError("scratch_resources_already_exist")
        if existing_ids:
            inspect_owned(environment, sorted(existing_ids))
        compose(environment, ["up", "-d", "postgres", "redis", "object_store"])
        record_containers(root, environment, ("postgres", "redis", "object_store"))
        seed_storage(environment)
        stage = "zebra_migrate"
        print("SCRATCH_STAGE=MIGRATE_NEW_DATABASES", flush=True)
        compose(environment, ["run", "--rm", "migrate"])
        stage = "host_migrate"
        compose(
            environment,
            [
                "run",
                "--rm",
                "trench_api",
                "python",
                "-m",
                "alembic",
                "-c",
                "infra/alembic.ini",
                "upgrade",
                "head",
            ],
        )
        seed_authority(environment)
        stage = "services"
        compose(environment, ["up", "-d", *ROLES])
        record_containers(root, environment, ROLES)
        state = json.loads((root / "state.json").read_text())
        os.environ["SSL_CERT_FILE"] = str(root / environment["SCRATCH_SCOPE"] / "ca-bundle.crt")
        ready(environment["HOST_ORIGIN"] + "/api/health/ready")
        ready(environment["BROKER_ORIGIN"] + "/health")
        stage = "identity"
        inputs = seed_identity(root, environment)
        inputs["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        inputs["ZEBRA_E2E_TLS_SPKI"] = state["spki"]
        pin_manifest(root, environment, build_id)
        stage = "actual_simple_answer"
        print("SCRATCH_STAGE=REAL_BROWSER_HOST_WORKER", flush=True)
        from joint_acceptance import run_joint

        evidence_dir = root / environment.get("EVIDENCE_SUBDIR", "evidence")
        code = run_joint({**os.environ, **inputs}, evidence_dir)
        result = json.loads((evidence_dir / "joint-result.json").read_text())
        return 0 if result.get("simple_answer") == "passed" else code
    except (E2EError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Safe stage/code only; private Env and upstream bodies stay out of evidence.
        reason = error.code if isinstance(error, E2EError) else type(error).__name__
        private_json(
            root / "failure.json", {"stage": stage, "reason": reason, "full_goal_passed": False}
        )
        print(f"SCRATCH_BLOCKED stage={stage} reason={reason}", flush=True)
        return 2
    finally:
        if not keep:
            stop_owned(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--stop", type=Path)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--zebra-images", type=Path)
    args = parser.parse_args()
    if args.stop:
        stop_owned(args.stop.resolve())
        print("SCRATCH_STOPPED recorded_containers_only volumes_preserved=true")
        return 0
    if not args.start:
        parser.error("choose --start or --stop")
    if args.zebra_images and not args.resume:
        parser.error("--zebra-images requires --resume of an owned scratch project")
    if args.resume:
        root = args.resume.resolve()
        if root.stat().st_mode & 0o077:
            raise E2EError("scratch_private_state_permissions")
        environment = json.loads((root / "state.json").read_text())["environment"]
        if args.zebra_images:
            refresh_zebra_images(root, environment, args.zebra_images.resolve())
    else:
        root, environment = prepare()
    print("SCRATCH_STATE=" + str(root), flush=True)
    return start(root, environment, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
