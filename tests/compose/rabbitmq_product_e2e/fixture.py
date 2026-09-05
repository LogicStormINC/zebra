"""Explicitly isolated product fixture. Never print/persist the returned environment."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROJECT = "rabbitmq-product-e2e"
WORKSPACE = Path("/Volumes/ZEBRATRENCH/rabbitmq-product-e2e")
ORIGINAL = Path("/Users/lukeding/Desktop/playground/2026/product/zebra-agent")
SECRETS = ORIGINAL / "docker/trench-acceptance/secrets"
ORIGINAL_WORKER = "zebra-trench-acceptance-zebra-worker-1"
OUTER_DOCKER_CONTEXT = "orbstack"
OUTER_DOCKER_ENDPOINT = "unix:///Users/lukeding/.orbstack/run/docker.sock"
RUNTIME_HOST = "tcp://host.docker.internal:2375"
REUSE_KEYS = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "ZEBRA_RUNTIME_IMAGE",
        "ZEBRA_RUNTIME_UID",
        "ZEBRA_RUNTIME_GID",
        "ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB",
    }
)
SCOPES = (
    "agent.run,event.read,evidence.read,entity.read,topic.read,source.read,history.read,"
    "artifact.read,artifact.publish,subscription.write"
)


def host_environment() -> dict[str, str]:
    # No inherited Compose, libpq, storage, model or Docker-host overrides.
    return {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_CONFIG", "TMPDIR")
        if key in os.environ
    }


def captured(args: list[str], *, env: dict[str, str] | None = None) -> str:
    effective_env = dict(env if env is not None else host_environment())

    def execute(command: list[str]) -> str:
        result = subprocess.run(
            command, env=effective_env, stdin=subprocess.DEVNULL, capture_output=True, text=True
        )
        if result.returncode:
            # Docker/Compose diagnostics can embed expanded credentials.
            raise RuntimeError("isolated fixture command failed; output withheld")
        return result.stdout

    if args and args[0] == "docker":
        if any(
            arg.split("=", 1)[0] in {"--context", "--host", "-H", "--config"} for arg in args[1:]
        ):
            raise ValueError("outer Docker engine overrides are forbidden")
        effective_env.pop("DOCKER_HOST", None)
        effective_env.pop("DOCKER_CONTEXT", None)
        prefix = ["docker", "--context", OUTER_DOCKER_CONTEXT]
        endpoint = execute(
            prefix
            + [
                "context",
                "inspect",
                OUTER_DOCKER_CONTEXT,
                "--format",
                "{{.Endpoints.docker.Host}}",
            ]
        ).strip()
        if endpoint != OUTER_DOCKER_ENDPOINT:
            raise ValueError("approved Docker context does not target the approved local endpoint")
        args = prefix + args[1:]
    return execute(args)


def reuse_worker_environment() -> dict[str, str]:
    clauses = " ".join(f'(eq $key "{key}")' for key in sorted(REUSE_KEYS))
    template = (
        '{{range .Config.Env}}{{$key := index (split . "=") 0}}'
        + "{{if or "
        + clauses
        + "}}{{println .}}{{end}}{{end}}"
    )
    raw = captured(["docker", "inspect", "--format", template, ORIGINAL_WORKER])
    values = dict(item.split("=", 1) for item in raw.splitlines() if "=" in item)
    return {key: values[key] for key in REUSE_KEYS if key in values}


def validate_workspace(path: Path) -> Path:
    if path != WORKSPACE or path.resolve() != WORKSPACE:
        raise ValueError("workspace must be the exact dedicated child, without symlinks")
    return path


def prepare_workspace() -> None:
    path = validate_workspace(WORKSPACE)
    path.mkdir(mode=0o777, parents=False, exist_ok=True)
    # The sandbox and application run as uid 65532, not the desktop user.
    path.chmod(0o777)


def build_environment(reused: dict[str, str] | None = None) -> dict[str, str]:
    """Return one run's shared secrets/config; caller retains this dict for its lifetime."""
    validate_workspace(WORKSPACE)
    if ROOT.resolve() == ORIGINAL.resolve():
        raise ValueError("run only from the isolated worktree")
    source = reuse_worker_environment() if reused is None else reused
    image = source.get("ZEBRA_RUNTIME_IMAGE", "")
    if not re.fullmatch(r".+@sha256:[0-9a-fA-F]{64}", image):
        raise ValueError("a pinned runtime image is required")
    if not source.get("DEEPSEEK_API_KEY"):
        raise ValueError("development model credential is required")
    for name in ("ca.crt", "tls.crt", "tls.key", "trench-host-grant-v1.pem"):
        if not (SECRETS / name).is_file():
            raise ValueError("existing acceptance TLS/signing material is missing")
    ca_hash = captured(
        ["openssl", "x509", "-in", str(SECRETS / "ca.crt"), "-noout", "-hash"]
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{8}", ca_hash):
        raise ValueError("invalid CA hash")
    password = secrets.token_hex(24)
    workload = secrets.token_hex(32)
    env = {
        "E2E_SOURCE_ROOT": str(ROOT),
        "E2E_SECRETS_ROOT": str(SECRETS),
        "E2E_WORKSPACE_ROOT": str(WORKSPACE),
        "E2E_CA_HASH": ca_hash,
        "E2E_POSTGRES_PASSWORD": password,
        "E2E_WORKLOAD_SECRET": workload,
        "E2E_API_TOKEN": secrets.token_hex(32),
        "E2E_CURSOR_KEY": secrets.token_hex(32),
        "E2E_MINIO_USER": "rabbitmq-e2e",
        "E2E_MINIO_PASSWORD": secrets.token_hex(32),
        "ZEBRA_DATABASE_URL": f"postgresql://e2e:{password}@postgres:5432/zebra_e2e",
        "E2E_ZEBRA_HOST_DSN": f"postgresql://e2e:{password}@127.0.0.1:28432/zebra_e2e",
        "E2E_TRENCH_HOST_DSN": f"postgresql+asyncpg://e2e:{password}@127.0.0.1:28432/trench_e2e",
        "E2E_TLS_URL": "https://127.0.0.1:28443",
        "E2E_BROKER_URL": "https://127.0.0.1:28443/broker/exchange",
        "E2E_CA_FILE": str(SECRETS / "ca.crt"),
        "E2E_WORKLOAD_IDENTITY": "rabbitmq-product-e2e-worker",
        "E2E_NAMESPACE": "rabbitmq-product-e2e",
        "E2E_HOST_NAMESPACE": "trench-rabbitmq-e2e",
        "E2E_POLICY_VERSION": "trench-native-v2",
        "E2E_ALLOWED_SCOPES": SCOPES,
        "DEEPSEEK_API_KEY": source["DEEPSEEK_API_KEY"],
        "ZEBRA_RUNTIME_IMAGE": image,
        "ZEBRA_RUNTIME_UID": source.get("ZEBRA_RUNTIME_UID", "65532"),
        "ZEBRA_RUNTIME_GID": source.get("ZEBRA_RUNTIME_GID", "65532"),
        "ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB": source.get("ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB", "10240"),
    }
    for service, image_name in {
        "API": "zebra-trench-acceptance-zebra-api",
        "WORKER": "zebra-trench-acceptance-zebra-worker",
        "BROKER": "zebra-trench-acceptance-trench-grant-broker",
    }.items():
        env[f"E2E_{service}_IMAGE"] = captured(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image_name]
        ).strip()
    validate_environment(env)
    return env


DATABASE_PAIRS = {
    "legacy": ("zebra_e2e", "trench_e2e"),
    "stage3": ("zebra_stage3_e2e", "trench_stage3_e2e"),
}


def _database_urls(password: str, pair: str) -> dict[str, str]:
    if pair not in DATABASE_PAIRS:
        raise ValueError("unsupported fixture database pair")
    zebra, trench = DATABASE_PAIRS[pair]
    return {
        "ZEBRA_DATABASE_URL": f"postgresql://e2e:{password}@postgres:5432/{zebra}",
        "E2E_ZEBRA_HOST_DSN": f"postgresql://e2e:{password}@127.0.0.1:28432/{zebra}",
        "E2E_TRENCH_HOST_DSN": f"postgresql+asyncpg://e2e:{password}@127.0.0.1:28432/{trench}",
    }


def database_pair(env: dict[str, str]) -> str:
    password = env.get("E2E_POSTGRES_PASSWORD", "")
    if not re.fullmatch(r"[0-9a-f]{48}", password):
        raise ValueError("fixture password must be generated locally")
    for pair in DATABASE_PAIRS:
        if all(env.get(key) == value for key, value in _database_urls(password, pair).items()):
            return pair
    raise ValueError("fixture database endpoints must form one exact approved pair")


def select_database_pair(env: dict[str, str], pair: str) -> dict[str, str]:
    """Pure copy: preserve every secret and validate the old target before selecting the new one."""
    validate_environment(env)
    selected = env | _database_urls(env["E2E_POSTGRES_PASSWORD"], pair)
    validate_environment(selected)
    return selected


def configure_broker(
    env: dict[str, str],
    rabbit: dict[str, str],
    *,
    publish_enabled: bool = False,
    consume_enabled: bool = False,
    fallback_enabled: bool = True,
) -> dict[str, str]:
    """Pure worker-only configuration; caller supplies credentials without any automatic reads."""
    validate_environment(env)
    if any(type(flag) is not bool for flag in (publish_enabled, consume_enabled, fallback_enabled)):
        raise ValueError("fixture broker flags must be boolean")
    configured = {k: v for k, v in env.items() if not k.startswith("ZEBRA_RABBIT_")}
    configured.update(
        {
            "ZEBRA_RABBIT_PUBLISH_ENABLED": str(publish_enabled).lower(),
            "ZEBRA_RABBIT_CONSUME_ENABLED": str(consume_enabled).lower(),
            "ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED": str(fallback_enabled).lower(),
        }
    )
    if publish_enabled or consume_enabled:
        if rabbit.get("RABBITMQ_AMQP_PORT") != "25672":
            raise ValueError("fixture broker endpoint must be isolated")
        for role in ("RELAY", "CONSUMER") if consume_enabled else ("RELAY",):
            password = rabbit.get(f"ZEBRA_RABBIT_{role}_PASSWORD", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", password):
                raise ValueError("invalid fixture broker credential")
            configured[f"ZEBRA_RABBIT_{role}_URL"] = (
                f"amqp://zebra-{role.lower()}:{password}@host.docker.internal:25672/%2Fzebra"
            )
    validate_environment(configured)
    return configured


def _validate_broker(env: dict[str, str]) -> None:
    flags = [
        env.get(key, default)
        for key, default in (
            ("ZEBRA_RABBIT_PUBLISH_ENABLED", "false"),
            ("ZEBRA_RABBIT_CONSUME_ENABLED", "false"),
            ("ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED", "true"),
        )
    ]
    if any(flag not in {"true", "false"} for flag in flags) or (
        flags[2] == "false" and flags[:2] != ["true", "true"]
    ):
        raise ValueError("fixture requires a recoverable execution path")
    for role in ("RELAY", "CONSUMER"):
        value = env.get(f"ZEBRA_RABBIT_{role}_URL")
        required = ("true" in flags[:2]) if role == "RELAY" else flags[1] == "true"
        if (value is not None or required) and not re.fullmatch(
            rf"amqp://zebra-{role.lower()}:[A-Za-z0-9_-]{{32,128}}@host\.docker\.internal:25672/%2Fzebra",
            value or "",
        ):
            raise ValueError("fixture broker endpoint or role is not approved")


def validate_environment(env: dict[str, str]) -> None:
    if any(key.startswith(("DOCKER_", "COMPOSE_", "PG")) for key in env):
        raise ValueError("ambient engine, compose or database overrides are forbidden")
    validate_workspace(Path(env["E2E_WORKSPACE_ROOT"]))
    if env["E2E_SOURCE_ROOT"] != str(ROOT) or env["E2E_SECRETS_ROOT"] != str(SECRETS):
        raise ValueError("source and read-only secrets paths must be pinned")
    if env["E2E_NAMESPACE"] != PROJECT or env["E2E_HOST_NAMESPACE"] != "trench-rabbitmq-e2e":
        raise ValueError("fixture namespaces must be isolated")
    password = env["E2E_POSTGRES_PASSWORD"]
    if not re.fullmatch(r"[0-9a-f]{48}", password):
        raise ValueError("fixture password must be generated locally")
    database_pair(env)
    _validate_broker(env)
    for key in ("E2E_API_IMAGE", "E2E_WORKER_IMAGE", "E2E_BROKER_IMAGE"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", env[key]):
            raise ValueError("application image dependency layers must be pinned")


def compose(env: dict[str, str], *args: str) -> str:
    """Run only this fixture's Compose project; expanded diagnostics stay private."""
    validate_environment(env)
    if not args or args[0] not in {"up", "ps", "stop", "down", "exec", "run"}:
        raise ValueError("unsupported fixture operation")
    if any(
        arg.split("=", 1)[0] in {"-f", "--file", "-p", "--project-name", "--env-file"}
        for arg in args
    ):
        raise ValueError("compose target overrides are forbidden")
    return captured(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "--file",
            str(ROOT / "docker/compose.rabbitmq-product-e2e.yml"),
            *args,
        ],
        env=host_environment() | env,
    )


def source_digest() -> str:
    """Secret-free current source receipt for the orchestrator's evidence."""
    digest = hashlib.sha256()
    for directory in ("apps", "packages", "configs"):
        for path in sorted((ROOT / directory).rglob("*")):
            if (
                not path.is_file()
                or path.suffix not in {".py", ".sql", ".toml", ".env"}
                or {".venv", "__pycache__", "node_modules"} & set(path.parts)
            ):
                continue
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
