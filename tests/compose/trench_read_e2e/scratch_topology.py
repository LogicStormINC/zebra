"""Fresh scratch inputs and read-only pins. Never discovers application identity."""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from support import E2EError

HERE = Path(__file__).resolve().parent
ZEBRA = HERE.parents[2]
TRENCH = ZEBRA.parent / "Trench"
PROVIDER_KEYS = {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"}
ROLES = (
    "postgres",
    "redis",
    "object_store",
    "zebra_api",
    "worker",
    "trench_api",
    "broker",
    "frontend",
    "proxy",
)


def docker(
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
    timeout: float = 30,
    input_text: str | None = None,
) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout,
        input=input_text,
        check=False,
    )
    if result.returncode:
        # stderr can contain Env, DSNs or JWTs. Caller records stage/code, never raw Docker output.
        raise E2EError("scratch_docker_command_failed")
    return result.stdout


def image_id(reference: str) -> str:
    return docker(["image", "inspect", reference, "--format", "{{.Id}}"]).strip()


def private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def provider_inputs() -> dict[str, str]:
    values = {key: os.environ[key] for key in PROVIDER_KEYS if os.environ.get(key)}
    if not values.get("DEEPSEEK_API_KEY"):
        # Explicitly authorized provider-only forwarding. No app identity/grant/cookie is retained.
        target = os.environ.get("ZEBRA_QA_PROVIDER_CONTAINER", "zebra-application-zebra-worker-1")
        row = json.loads(docker(["container", "inspect", target]))[0]
        values.update(
            {
                key: value
                for entry in row["Config"]["Env"]
                for key, value in [entry.split("=", 1)]
                if key in PROVIDER_KEYS
            }
        )
    if not values.get("DEEPSEEK_API_KEY"):
        raise E2EError("real_provider_credential_unavailable")
    return values


def make_tls(root: Path, scope: str) -> str:
    from ipaddress import ip_address

    import certifi
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, scope + "-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, scope + "-proxy")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(scope + "-proxy"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    for file, content in {
        "ca.crt": ca.public_bytes(serialization.Encoding.PEM),
        "tls.crt": leaf.public_bytes(serialization.Encoding.PEM),
        "tls.key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "broker.pem": rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "ca-bundle.crt": Path(certifi.where()).read_bytes()
        + ca.public_bytes(serialization.Encoding.PEM),
    }.items():
        path = root / file
        path.write_bytes(content)
        # Parent is 0700; only explicitly selected read-only files reach containers (UID 65532).
        path.chmod(0o644)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(sha256(spki).digest()).decode()


def prepare() -> tuple[Path, dict[str, str]]:
    scratch_id = "qa-" + secrets.token_hex(6)
    scope = "zebra-progress-e2e-" + scratch_id
    root = Path(tempfile.mkdtemp(prefix="zebra-joint-qa-")).resolve()
    root.chmod(0o700)
    secret_root = root / scope
    secret_root.mkdir(mode=0o700)
    shutil.copyfile(HERE / "worker_observation.py", secret_root / "worker_observation.py")
    (secret_root / "worker_observation.py").chmod(0o644)
    ports = {}
    sockets = []
    for name in (
        "PG",
        "REDIS",
        "MINIO",
        "API",
        "HOST_API",
        "BROKER_API",
        "FRONTEND",
        "HOST_TLS",
        "BROKER_TLS",
        "ZEBRA_TLS",
        "ADMIN",
    ):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        sockets.append(listener)
        ports[name + "_PORT"] = str(listener.getsockname()[1])
    for listener in sockets:
        listener.close()
    values = {
        **ports,
        "SCRATCH_ID": scratch_id,
        "SCRATCH_SCOPE": scope,
        "SECRET_ROOT": str(secret_root),
        "PG_SECRET": secrets.token_hex(24),
        "AUTH_SECRET": secrets.token_hex(32),
        "GRANT_SECRET": secrets.token_hex(32),
        "HOST_TOOL_SECRET": secrets.token_hex(32),
        "CURSOR_SECRET": secrets.token_hex(32),
        "MINIO_USER": "qa" + secrets.token_hex(8),
        "MINIO_SECRET": secrets.token_hex(24),
    }
    values.update(
        HOST_ORIGIN="https://127.0.0.1:" + ports["HOST_TLS_PORT"],
        BROKER_ORIGIN="https://127.0.0.1:" + ports["BROKER_TLS_PORT"],
    )
    for prefix, suffix in (("ZEBRA", "zebra"), ("TRENCH", "trench")):
        values[prefix + "_DATABASE_URL"] = (
            f"postgresql://qa:{values['PG_SECRET']}@{scope}-postgres:5432/{scope}_{suffix}"
        )
    for field, reference in {
        "API_IMAGE": "zebra-application-zebra-api:latest",
        "WORKER_IMAGE": "zebra-application-zebra-worker:latest",
        "MIGRATE_IMAGE": "zebra-application-zebra-migrate:latest",
        "PG_IMAGE": "postgres:16-alpine",
        "REDIS_IMAGE": "redis:8.2.1-alpine",
        "MINIO_IMAGE": "quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z",
        "CADDY_IMAGE": "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/caddy:2-alpine",
    }.items():
        values[field] = image_id(os.environ.get("ZEBRA_QA_" + field, reference))
    spki = make_tls(secret_root, scope)
    caddy = "{\n admin 0.0.0.0:2019\n auto_https off\n}\n"
    for port, upstream in ((8444, "broker:8090"), (8445, "zebra_api:8000")):
        caddy += (
            f"https://: {port}".replace(": ", ":") + " {\n"
            " tls /secrets/tls.crt /secrets/tls.key\n"
            f" reverse_proxy {scope}-{upstream} {{\n flush_interval -1\n }}\n}}\n"
        )
    caddy += (
        "https://:8443 {\n tls /secrets/tls.crt /secrets/tls.key\n"
        f" handle /api/* {{\n reverse_proxy {scope}-trench_api:8000 {{\n"
        " flush_interval -1\n }\n }\n"
        f" handle {{\n reverse_proxy {scope}-frontend:3000\n }}\n}}\n"
    )
    (secret_root / "Caddyfile").write_text(caddy)
    private_json(root / "state.json", {"environment": values, "spki": spki, "containers": {}})
    return root, values


def inspect_owned(environment: dict[str, str], names: list[str]) -> list[dict[str, Any]]:
    rows = cast(list[dict[str, Any]], json.loads(docker(["container", "inspect", *names])))
    scope, scratch_id = environment["SCRATCH_SCOPE"], environment["SCRATCH_ID"]
    for row in rows:
        if (
            not row["Name"].lstrip("/").startswith(scope + "-")
            or row["Config"]["Labels"].get("zebra.e2e.scratch_id") != scratch_id
            or any(not name.startswith(scope + "-") for name in row["NetworkSettings"]["Networks"])
            or row["HostConfig"]["Privileged"]
        ):
            raise E2EError("scratch_target_not_owned")
    return rows


def wait_running(environment: dict[str, str], role: str, timeout: int = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = inspect_owned(environment, [environment["SCRATCH_SCOPE"] + "-" + role])[0]
        if row["State"]["Running"]:
            return row
        if row["State"]["Status"] in {"exited", "dead"}:
            raise E2EError("scratch_service_exited_" + role)
        time.sleep(0.2)
    raise E2EError("scratch_service_start_timeout")


def pin_manifest(root: Path, environment: dict[str, str], build_id: str) -> dict[str, Any]:
    scope = environment["SCRATCH_SCOPE"]
    rows = inspect_owned(environment, [scope + "-" + role for role in ROLES])
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "scratch_id": environment["SCRATCH_ID"],
        "namespace_id": scope,
        "frontend_url": environment["HOST_ORIGIN"],
        "frontend_build_id": build_id,
        "proxy_admin_url": f"http://127.0.0.1:{environment['ADMIN_PORT']}/config/",
        "endpoint_containers": {
            name: "proxy"
            for name in (
                "bff_url",
                "read_tools_url",
                "trench_health_url",
                "zebra_base_url",
                "zebra_health_url",
                "grant_exchange_url",
            )
        },
        "containers": {},
    }
    for role, row in zip(ROLES, rows, strict=True):
        pins = {
            mount["Source"]: sha256(Path(mount["Source"]).read_bytes()).hexdigest()
            for mount in row["Mounts"]
            if mount["Type"] == "bind"
        }
        manifest["containers"][role] = {
            "id": row["Id"],
            "image_id": row["Image"],
            "bind_sha256": pins,
            "config_sha256": sha256(
                json.dumps(row["Config"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    private_json(root / "isolation.json", manifest)
    return manifest
