"""Pinned scratch resources; observation never adopts or repairs application state."""

from __future__ import annotations

import json
import os
import re
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from support import Config


def host_qa_mode() -> bool:
    """Only a trusted, explicitly frozen QA process may use host operator authority."""
    from support import ConfigError

    mode = os.environ.get("ZEBRA_E2E_OPERATOR_MODE", "sidecar")
    if mode not in {"sidecar", "host"}:
        raise ConfigError([], ["ZEBRA_E2E_OPERATOR_MODE"])
    if mode == "host" and os.environ.get("ZEBRA_E2E_P1_FROZEN") != "1":
        raise ConfigError([], ["ZEBRA_E2E_P1_FROZEN"])
    return mode == "host"


def validate_base(config: Config, *, simple_slice: bool = False) -> dict[str, Any]:
    """Read-only Docker/DB proof, shared with the nine legacy smokes."""
    from support import ConfigError, E2EError, origin, postgres_probe, validate_endpoint
    from support import subprocess as transport_process

    host_operator = host_qa_mode()
    without_sidecar = simple_slice or host_operator
    try:
        path = Path(config.isolation_manifest)
        if path.stat().st_size > 32768:
            raise ValueError
        manifest = json.loads(path.read_text(encoding="utf-8"))
        scratch_id = manifest["scratch_id"]
        if not isinstance(scratch_id, str) or not re.fullmatch(r"[a-z0-9-]{8,64}", scratch_id):
            raise ValueError
        scope = f"zebra-progress-e2e-{scratch_id}"
        if manifest["namespace_id"] != scope:
            raise ValueError
        specs = manifest["containers"]
        roles = {
            "trench_api",
            "zebra_api",
            "worker",
            "broker",
            "operator",
            "redis",
            "object_store",
            "postgres",
        }
        if without_sidecar:
            roles.remove("operator")
        if not isinstance(specs, dict) or not roles.issubset(specs) or len(specs) > 12:
            raise ValueError
        ids = [spec["id"] for spec in specs.values()]
        if len(set(ids)) != len(ids) or any(
            not re.fullmatch(r"[a-f0-9]{64}", item) for item in ids
        ):
            raise ValueError
        inspected = transport_process.run(
            ["docker", "container", "inspect", *ids],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        rows = {row["Id"]: row for row in json.loads(inspected.stdout)}
        envs = {}
        for role, spec in specs.items():
            row = rows[spec["id"]]
            if not row["State"]["Running"] or not row["Name"].lstrip("/").startswith(scope + "-"):
                raise ValueError
            if host_operator and role == "worker" and row["Name"].lstrip("/") != scope + "-worker":
                raise ValueError
            if row["Config"]["Labels"].get("zebra.e2e.scratch_id") != scratch_id:
                raise ValueError
            if not row["NetworkSettings"]["Networks"] or any(
                not name.startswith(scope + "-") for name in row["NetworkSettings"]["Networks"]
            ):
                raise ValueError
            digest = sha256(
                json.dumps(row["Config"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if digest != spec["config_sha256"]:
                raise ValueError
            envs[role] = dict(item.split("=", 1) for item in row["Config"]["Env"])
        endpoints = {
            "bff_url": "trench_api",
            "read_tools_url": "trench_api",
            "trench_health_url": "trench_api",
            "trench_snapshot_url": "operator",
            "zebra_base_url": "zebra_api",
            "zebra_health_url": "zebra_api",
            "grant_exchange_url": "broker",
            "worker_restart_url": "operator",
            "trench_object_store_url": "object_store",
            "zebra_object_store_url": "object_store",
            "trench_database_dsn": "postgres",
            "zebra_database_dsn": "postgres",
            "trench_redis_url": "redis",
            "zebra_redis_url": "redis",
        }
        if without_sidecar:
            del endpoints["trench_snapshot_url"], endpoints["worker_restart_url"]
        for field, service in endpoints.items():
            parsed = urlsplit(getattr(config, field))
            role = (
                service
                if field.endswith(("_dsn", "_redis_url"))
                else manifest.get("endpoint_containers", {}).get(field, service)
            )
            row = rows[specs[role]["id"]]
            ports = row["NetworkSettings"]["Ports"].values()
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not any(
                binding["HostIp"] in {"127.0.0.1", "::1"}
                and int(binding["HostPort"]) == parsed.port
                for bindings in ports
                if bindings
                for binding in bindings
            ):
                raise ValueError
        db_names = [
            urlsplit(dsn).path.lstrip("/")
            for dsn in (
                config.trench_database_dsn,
                config.zebra_database_dsn,
            )
        ]
        if len(set(db_names)) != 2 or any(not name.startswith(scope + "_") for name in db_names):
            raise ValueError
        pg = rows[specs["postgres"]["id"]]["NetworkSettings"]
        pg_hosts = {
            value
            for network in pg["Networks"].values()
            for value in [network["IPAddress"], *(network.get("Aliases") or [])]
        }
        if "5432/tcp" not in pg["Ports"]:
            raise ValueError
        for role, variable, expected in (
            ("zebra_api", "ZEBRA_DATABASE_URL", db_names[1]),
            ("worker", "ZEBRA_DATABASE_URL", db_names[1]),
            ("trench_api", "DATABASE_URL", db_names[0]),
            ("operator", "TRENCH_SNAPSHOT_DATABASE_DSN", db_names[0]),
        ):
            if without_sidecar and role == "operator":
                continue
            dsn = urlsplit(envs[role][variable])
            if (
                dsn.path.lstrip("/") != expected
                or dsn.hostname not in pg_hosts
                or (dsn.port or 5432) != 5432
            ):
                raise ValueError
        if any(
            envs[role]["ZEBRA_DEPLOYMENT_NAMESPACE"] != scope for role in ("worker", "zebra_api")
        ):
            raise ValueError
        if envs["broker"]["ZEBRA_GRANT_BROKER_NAMESPACE_ID"] != scope:
            raise ValueError
        if envs["broker"]["ZEBRA_GRANT_BROKER_ORIGIN"] != origin(config.bff_url):
            raise ValueError
        if envs["broker"]["ZEBRA_GRANT_BROKER_ISSUER"] != origin(config.grant_exchange_url):
            raise ValueError
        if (
            not without_sidecar
            and envs["operator"]["E2E_WORKER_CONTAINER"] != specs["worker"]["id"]
        ):
            raise ValueError
        if validate_endpoint(envs["trench_api"]["ZEBRA_TASKS_URL"]) != config.runtime_tasks_url:
            raise ValueError
        postgres_probe(config.trench_database_dsn)
        postgres_probe(config.zebra_database_dsn)
        return rows
    except (
        E2EError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.SubprocessError,
    ):
        raise ConfigError([], ["scratch_isolation"]) from None


def _dials(value: object) -> set[str]:
    if isinstance(value, dict):
        result = {value["dial"]} if isinstance(value.get("dial"), str) else set()
        return result.union(*(_dials(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_dials(child) for child in value))
    return set()


def _native_endpoint(url: str, row: Any, port: int) -> None:
    parsed = urlsplit(url)
    aliases = {
        item
        for network in row["NetworkSettings"]["Networks"].values()
        for item in [network["IPAddress"], *(network.get("Aliases") or [])]
    }
    if parsed.hostname not in aliases or parsed.port != port:
        raise ValueError("unproved upstream")


def joint_preflight(config: Config) -> dict[str, object]:
    """No DDL, adoption, renewal, POST, Docker restart or credential export."""
    from support import ConfigError, cookie_headers, join_url, request, require_status

    phase = "base"
    try:
        rows = validate_base(config, simple_slice=True)
        manifest = json.loads(Path(config.isolation_manifest).read_text())
        if manifest["schema_version"] != 2:
            raise ValueError
        scope = manifest["namespace_id"]
        specs = manifest["containers"]
        roles = {role: rows[spec["id"]] for role, spec in specs.items()}
        phase = "image_mounts"
        images = {}
        for role, row in roles.items():
            image = specs[role]["image_id"]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image) or row["Image"] != image:
                raise ValueError
            images[role] = image
            host = row["HostConfig"]
            if (
                host.get("Privileged")
                or host.get("NetworkMode") == "host"
                or host.get("PidMode") == "host"
                or host.get("ExtraHosts")
            ):
                raise ValueError
            for mount in row["Mounts"]:
                if mount["Type"] == "volume":
                    if not mount["Name"].startswith(scope + "-"):
                        raise ValueError
                elif mount["Type"] == "bind":
                    source = Path(mount["Source"]).resolve()
                    root = Path(config.isolation_manifest).resolve().parent / scope
                    pin = specs[role].get("bind_sha256", {}).get(str(source))
                    if (
                        not source.is_relative_to(root)
                        or not source.is_file()
                        or source.stat().st_size > 1_048_576
                        or mount["RW"] is not False
                        or sha256(source.read_bytes()).hexdigest() != pin
                    ):
                        raise ValueError
                else:
                    raise ValueError
        envs = {
            role: dict(item.split("=", 1) for item in row["Config"]["Env"])
            for role, row in roles.items()
        }
        phase = "internal_endpoints"
        secret = envs["trench_api"]["TRENCH_AI_AUTH_SECRET"]
        if len(secret) < 32 or secret.startswith("trench-ai-dev-secret"):
            raise ValueError
        # Provider keys are allowed inputs; only application session identity must be fresh.
        _native_endpoint(config.runtime_tasks_url, roles["proxy"], 8445)
        for variable, port in (
            ("ZEBRA_AGUI_COMMAND_URL", 8445),
            ("ZEBRA_HOST_GRANT_EXCHANGE_URL", 8444),
        ):
            _native_endpoint(envs["trench_api"][variable], roles["proxy"], port)
        for variable in (
            "ZEBRA_GRANT_BROKER_TRENCH_ME_URL",
            "ZEBRA_GRANT_BROKER_TRENCH_SOURCES_URL",
        ):
            _native_endpoint(envs["broker"][variable], roles["proxy"], 8443)
        admin = urlsplit(manifest["proxy_admin_url"])
        bindings = roles["proxy"]["NetworkSettings"]["Ports"]["2019/tcp"]
        if admin.hostname != "127.0.0.1" or not any(
            item["HostIp"] == "127.0.0.1" and int(item["HostPort"]) == admin.port
            for item in bindings
        ):
            raise ValueError
        phase = "proxy_routes"
        response = request("GET", manifest["proxy_admin_url"], timeout=5)
        require_status(response, {200})
        servers = response.json()["apps"]["http"]["servers"]  # type: ignore[index]
        expected = {
            8443: {f"{scope}-trench_api:8000", f"{scope}-frontend:3000"},
            8444: {f"{scope}-broker:8090"},
            8445: {f"{scope}-zebra_api:8000"},
        }
        seen = set()
        for server in servers.values():
            listeners = server["listen"]
            ports = {int(listener.rsplit(":", 1)[1]) for listener in listeners}
            if (
                len(ports) != 1
                or not ports.issubset(expected)
                or _dials(server) != expected[next(iter(ports))]
            ):
                raise ValueError
            seen.update(ports)
        if seen != set(expected) or manifest["frontend_url"] != config.bff_url:
            raise ValueError
        phase = "frontend_build"
        build_id = manifest["frontend_build_id"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", build_id):
            raise ValueError
        directory = roles["frontend"]["Config"].get("WorkingDir", "/app")
        if directory not in {"/app", "/app/frontend"}:
            raise ValueError
        built = subprocess.run(
            ["docker", "exec", specs["frontend"]["id"], "cat", directory + "/.next/BUILD_ID"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if built != build_id:
            raise ValueError
        phase = "principal"
        response = request(
            "GET",
            join_url(config.bff_url, f"/_next/static/{build_id}/_buildManifest.js"),
            timeout=5,
        )
        require_status(response, {200})
        response = request(
            "GET",
            join_url(config.bff_url, "/api/trench-ai/me"),
            headers=cookie_headers(config),
            timeout=5,
        )
        require_status(response, {200})
        viewer = response.json()["data"]["viewer"]  # type: ignore[index]
        if viewer["user_id"] != config.user_id or viewer["workspace_id"] != config.workspace_id:
            raise ValueError
        return {
            "scope": "read_only_scratch_preflight_not_live_acceptance",
            "namespace_id": scope,
            "containers": {role: spec["id"] for role, spec in specs.items()},
            "images": images,
            "frontend_build_id": build_id,
            "full_goal_passed": False,
        }
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        raise ConfigError([], ["joint_scratch_" + phase]) from None
