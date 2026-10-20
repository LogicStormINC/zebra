"""Boot prebuilt Runtime images with disposable PG/Redis/S3, without a business Host.

Requires a real gVisor engine and its mTLS client certificates. Does not create a
Task or call a model. Only resources with this run's random names are removed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]


def run(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=240,
    )
    if result.returncode:
        raise RuntimeError(f"{args[:3]}: {result.stderr or result.stdout}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-url", required=True)
    parser.add_argument("--engine-cert-dir", type=Path, required=True)
    parser.add_argument("--info-proxy", default="")
    parser.add_argument("--worker-image", default="zebra-decouple-check:worker")
    parser.add_argument("--api-image", default="zebra-decouple-check:api")
    parser.add_argument("--migrate-image", default="zebra-decouple-check:migrate")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    name = f"zebra-independent-{uuid4().hex[:10]}"
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("ZEBRA_", "TRENCH_", "COMPOSE_", "DEEPSEEK_"))
    }
    deps: list[str] = []
    network_created = False
    report: dict[str, object] = {"status": "FAIL", "project": name}
    with tempfile.TemporaryDirectory(prefix=name + "-") as temporary:
        scratch = Path(temporary)
        certs = scratch / "engine-certs"
        certs.mkdir()
        for filename in ("ca.pem", "cert.pem", "key.pem"):
            target = certs / filename
            shutil.copyfile(args.engine_cert_dir / filename, target)
            # Only disposable engine credentials; match root-group supplemental access.
            target.chmod(0o640)
        certs.chmod(0o755)
        secret = uuid4().hex
        values = {
            "ZEBRA_APPLICATION_NETWORK": name,
            "ZEBRA_DATABASE_URL": f"postgresql://zebra:{secret}@postgres:5432/zebra",
            "ZEBRA_RUNTIME_CLASS": "gvisor",
            "ZEBRA_RUNTIME_IMAGE": "python@sha256:" + "a" * 64,
            "ZEBRA_RUNTIME_DEFER_PROVISION": "true",
            "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
            "ZEBRA_DEPLOYMENT_NAMESPACE": name,
            "ZEBRA_AUTHORITY_ISSUER": "https://issuer.example.invalid",
            "ZEBRA_HISTORY_SCOPE_NAMESPACE": name + "-history",
            "ZEBRA_CONTINUATION_SCOPE_NAMESPACE": name + "-continuation",
            "ZEBRA_MEMORY_CURSOR_SIGNING_KEY": uuid4().hex + uuid4().hex,
            "ZEBRA_S3_ENDPOINT": "http://minio:9000",
            "ZEBRA_S3_BUCKET": "runtime-smoke",
            "ZEBRA_S3_ACCESS_KEY": "runtime-smoke",
            "ZEBRA_S3_SECRET_KEY": secret,
            "ZEBRA_LIVE_REDIS_URL": "redis://redis:6379/0",
            "ZEBRA_DOCKER_SOCKET_GID": "0",
            "ZEBRA_WORKSPACE_VOLUME_ROOT": str(scratch / "workspace"),
            "DEEPSEEK_API_KEY": "boot-only-no-model-calls",
        }
        (scratch / "workspace").mkdir(mode=0o777)
        environment.update(values)
        env_file = scratch / "runtime.env"
        env_file.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
        env_file.chmod(0o600)
        # Compose's actual base is exercised; only images/engine/host ports differ.
        workspace_mount = f"{scratch / 'workspace'}:{scratch / 'workspace'}"
        overrides = "services:\n"
        for service, image in (
            ("zebra-api", args.api_image), ("zebra-worker", args.worker_image),
            ("zebra-migrate", args.migrate_image),
        ):
            overrides += f"  {service}:\n    image: {json.dumps(image)}\n    build: !reset null\n"
            if service == "zebra-api":
                overrides += "    ports: !override []\n"
            if service == "zebra-worker":
                overrides += (
                    "    environment:\n"
                    f"      DOCKER_HOST: {json.dumps(args.engine_url)}\n"
                    "      DOCKER_TLS_VERIFY: '1'\n"
                    "      DOCKER_CERT_PATH: /run/engine-certs\n"
                    f"      ZEBRA_OCI_INFO_CONNECT_PROXY: {json.dumps(args.info_proxy)}\n"
                    f"    group_add: !override [{os.getgid()}]\n"
                    "    volumes: !override\n"
                    f"      - {json.dumps(str(certs) + ':/run/engine-certs:ro')}\n"
                    f"      - {json.dumps(workspace_mount)}\n"
                )
        override_file = scratch / "boot.yml"
        override_file.write_text(overrides)
        compose = (
            "docker", "compose", "--env-file", str(env_file), "-p", name,
            "-f", str(ROOT / "docker/compose.application.yml"), "-f", str(override_file),
        )

        def app(*arguments: str) -> str:
            return run(*compose, *arguments, env=environment)

        def python(code: str) -> str:
            return app(
                "run", "--rm", "--no-deps", "--entrypoint", "python", "zebra-migrate", "-c", code,
            )

        try:
            rendered = json.loads(app("config", "--format", "json"))
            assert set(rendered["services"]) == {"zebra-api", "zebra-worker", "zebra-migrate"}
            assert "trench" not in json.dumps(rendered).lower()
            run("docker", "network", "create", name)
            network_created = True
            for alias, image, settings, command in (
                ("postgres", "postgres:17.5-alpine3.21", {
                    "POSTGRES_USER": "zebra", "POSTGRES_PASSWORD": secret, "POSTGRES_DB": "zebra",
                }, ()),
                ("redis", "redis:8.2.1-alpine", {}, ()),
                ("minio", "quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z", {
                    "MINIO_ROOT_USER": "runtime-smoke", "MINIO_ROOT_PASSWORD": secret,
                }, ("server", "/data")),
            ):
                container = name + "-" + alias
                deps.append(container)
                options = tuple(value for k, v in settings.items() for value in ("-e", f"{k}={v}"))
                run("docker", "run", "-d", "--name", container, "--network", name,
                    "--network-alias", alias, *options, image, *command)
            for _ in range(60):
                ready = subprocess.run(
                    ["docker", "exec", name + "-postgres", "pg_isready", "-U", "zebra"],
                    capture_output=True, timeout=5,
                )
                if ready.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("scratch PostgreSQL did not start")
            python(
                "import os; from botocore.session import Session; "
                "c=Session().create_client('s3',endpoint_url=os.environ['ZEBRA_S3_ENDPOINT'],"
                "aws_access_key_id=os.environ['ZEBRA_S3_ACCESS_KEY'],"
                "aws_secret_access_key=os.environ['ZEBRA_S3_SECRET_KEY'],region_name='us-east-1'); "
                "c.create_bucket(Bucket='runtime-smoke'); "
                "c.put_bucket_versioning(Bucket='runtime-smoke',"
                "VersioningConfiguration={'Status':'Enabled'}); "
                "c.put_object(Bucket='runtime-smoke',Key='preservation-probe',Body=b'unchanged')"
            )
            app("up", "-d", "--no-build", "zebra-migrate")
            app("wait", "zebra-migrate")
            python(
                "import os; from agent_storage.postgres.host_auth import "
                "HostRegistryRecord,PostgresHostAuthorityStore; "
                "PostgresHostAuthorityStore(os.environ['ZEBRA_DATABASE_URL'],"
                "deployment_namespace=os.environ['ZEBRA_DEPLOYMENT_NAMESPACE']).upsert_registry("
                "HostRegistryRecord(host_app_id='neutral-host',namespace_id='neutral-host',"
                "issuer='https://issuer.example.invalid',audience='runtime',"
                "jwks_uri='https://issuer.example.invalid/jwks',"
                "allowed_origins=('https://product.example.invalid',),"
                "algorithms=('RS256',),policy_version='v1'))"
            )
            app("up", "-d", "--no-build", "--wait", "--wait-timeout", "120",
                "zebra-api", "zebra-worker")
            health_code = (
                "import json,urllib.request,urllib.error; "
                "r=urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=5); "
                "assert r.status==200; print(r.read().decode())"
            )
            report["health"] = app("exec", "-T", "zebra-api", "python", "-c", health_code)
            denied = app("exec", "-T", "zebra-api", "python", "-c",
                "import urllib.request,urllib.error\ntry:\n "
                "urllib.request.urlopen('http://127.0.0.1:8000/tasks',timeout=5)\n"
                "except urllib.error.HTTPError as e:\n"
                " assert e.code in (401,403),e.code; print(e.code)\n"
                "else:\n raise AssertionError('anonymous task access admitted')")
            report["anonymous_status"] = int(denied)
            report["runtime_preflight"] = app("exec", "-T", "zebra-worker", "python", "-m",
                "zebra_agent_worker.runtime_preflight")
            app("restart", "zebra-api")
            app("up", "-d", "--no-build", "--wait", "--wait-timeout", "120", "zebra-api")
            report["health_after_restart"] = app(
                "exec", "-T", "zebra-api", "python", "-c", health_code,
            )
            python(
                "import os; from botocore.session import Session; "
                "c=Session().create_client('s3',endpoint_url=os.environ['ZEBRA_S3_ENDPOINT'],"
                "aws_access_key_id=os.environ['ZEBRA_S3_ACCESS_KEY'],"
                "aws_secret_access_key=os.environ['ZEBRA_S3_SECRET_KEY'],region_name='us-east-1'); "
                "assert c.get_object(Bucket='runtime-smoke',"
                "Key='preservation-probe')['Body'].read()==b'unchanged'; "
                "from agent_storage.postgres.host_auth import PostgresHostAuthorityStore; "
                "s=PostgresHostAuthorityStore(os.environ['ZEBRA_DATABASE_URL'],"
                "deployment_namespace=os.environ['ZEBRA_DEPLOYMENT_NAMESPACE']); "
                "assert s.list_registries()"
            )
            report.update(status="PASS", data_probe="object and Host registry survive API restart")
        except Exception as exc:
            report["error"] = str(exc)
            raise
        finally:
            try:
                (evidence / "boot.log").write_text(app("logs", "--no-color"))
            finally:
                cleanup_errors = []
                commands = [(*compose, "down", "--remove-orphans")]
                commands.extend(("docker", "rm", "-fv", container) for container in deps)
                if network_created:
                    commands.append(("docker", "network", "rm", name))
                for command in commands:
                    try:
                        run(*command, env=environment)
                    except RuntimeError as exc:
                        cleanup_errors.append(str(exc))
                if cleanup_errors:
                    report.update(status="FAIL", cleanup_errors=cleanup_errors)
                (evidence / "boot-result.json").write_text(json.dumps(report, indent=2) + "\n")
                if cleanup_errors:
                    raise RuntimeError("scratch cleanup failed; see boot-result.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
