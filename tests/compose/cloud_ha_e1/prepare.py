"""Prepare private files for a NEW synthetic E1 environment; never starts services."""

import argparse
import json
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def private(path: Path, value: str) -> None:
    with path.open("x") as stream:
        path.chmod(0o600)
        stream.write(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    tls = root / "tls"
    tls.mkdir(mode=0o700)
    commands = [
        "req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt -days 7 "
        "-subj '/CN=Zebra synthetic E1 CA'",
        "req -newkey rsa:2048 -nodes -keyout server.key -out server.csr "
        "-subj '/CN=Zebra synthetic E1'",
        "x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial "
        "-out server.crt -days 7 -extfile extensions.cnf",
        "genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out broker.key",
        "req -newkey rsa:2048 -nodes -keyout model.key -out model.csr -subj /CN=api.deepseek.com",
        "x509 -req -in model.csr -CA ca.crt -CAkey ca.key -CAcreateserial "
        "-out model.crt -days 7 -extfile model.ext",
    ]
    (tls / "model.ext").write_text(
        "subjectAltName=DNS:api.deepseek.com\nextendedKeyUsage=serverAuth\n"
    )
    (tls / "extensions.cnf").write_text(
        "subjectAltName=IP:127.0.0.1,IP:192.168.101.7,IP:192.168.139.232,IP:192.168.139.154\n"
        "extendedKeyUsage=serverAuth\n"
    )
    with (root / "openssl.log").open("w") as log:
        for command in commands:
            subprocess.run(
                ["openssl", *shlex.split(command)], cwd=tls, check=True, stdout=log, stderr=log
            )
    for path in tls.glob("*.key"):
        path.chmod(0o600)
    (tls / "ca.crt").chmod(0o644)
    (tls / "server.crt").chmod(0o644)
    shutil.copyfile(tls / "server.key", tls / "pg.key")
    (tls / "pg.key").chmod(0o600)
    values = {
        key: secrets.token_urlsafe(32)
        for key in ("pg_admin", "pg_app", "redis", "s3_secret", "cursor")
    }
    private(root / "credentials.json", json.dumps(values))
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[3] / "scripts/provision_rabbitmq.py"),
            "prepare",
            "--env-file",
            str(root / "rabbit.env"),
        ],
        check=True,
    )
    rabbit = dict(line.split("=", 1) for line in (root / "rabbit.env").read_text().splitlines())
    private(
        root / "principals.json",
        json.dumps(
            [
                dict(
                    principal=f"e1-principal-{i:02}",
                    workspace=f"e1-workspace-{i:02}",
                    token=secrets.token_urlsafe(32),
                )
                for i in range(32)
            ]
        ),
    )
    namespace = "ha-e1-20261102"
    budget = dict(
        pool=3,
        normal=8,
        read=2,
        control=2,
        probe=1,
        max_connections=256,
        server_reserved=3,
        external=4,
        execution_slots=4,
        fleet=dict(api=2, worker=2, executor=8, cleanup=2, scheduler=1),
    )
    env = {
        "ZEBRA_PROFILE": "cloud",
        "ZEBRA_DATABASE_URL": f"postgresql://ha_app:{values['pg_app']}@127.0.0.1:25432/ha_e1?sslmode=verify-full&sslrootcert=/e1/ca.crt",
        "ZEBRA_DATABASE_BUDGET_JSON": json.dumps(budget, separators=(",", ":")),
        "ZEBRA_DEPLOYMENT_NAMESPACE": namespace,
        "ZEBRA_AUTHORITY_ISSUER": "https://127.0.0.1:28444",
        "ZEBRA_HISTORY_SCOPE_NAMESPACE": namespace,
        "ZEBRA_CONTINUATION_SCOPE_NAMESPACE": namespace,
        "ZEBRA_MEMORY_CURSOR_SIGNING_KEY": values["cursor"],
        "ZEBRA_S3_ENDPOINT": "https://127.0.0.1:29000",
        "ZEBRA_S3_BUCKET": "ha-e1-artifacts",
        "ZEBRA_S3_ACCESS_KEY": "ha-e1",
        "ZEBRA_S3_SECRET_KEY": values["s3_secret"],
        "ZEBRA_LIVE_REDIS_URL": f"rediss://:{values['redis']}@127.0.0.1:26379/0?ssl_ca_certs=/e1/ca.crt",
        "ZEBRA_RUNTIME_CLASS": "gvisor",
        "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        "ZEBRA_RUNTIME_IMAGE": (
            "python:3.12-slim-bookworm@sha256:"
            "d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
        ),
        "ZEBRA_RUNTIME_CPUS": ".25",
        "ZEBRA_RUNTIME_MEMORY_MB": "256",
        "ZEBRA_RUNTIME_PIDS": "64",
        "ZEBRA_RUNTIME_TMPFS_MB": "64",
        "ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB": "512",
        "ZEBRA_WORKSPACE_VOLUME_ROOT": (
            "/var/lib/docker/volumes/zebra-ha-e1-20261102-workspaces/_data"
        ),
        "ZEBRA_MODEL_PROVIDER": "deepseek",
        "ZEBRA_MODEL_API_KEY_ENV": "ZEBRA_E2E_MODEL_API_KEY",
        "ZEBRA_MODEL_BASE_URL": "https://api.deepseek.com",
        "ZEBRA_MODEL_NAME": "deepseek-v4-pro",
        "ZEBRA_DEEPSEEK_REVIEWER_PROFILE": "deepseek-v4-pro-reviewer-v1",
        "NO_PROXY": "127.0.0.1,localhost,api.deepseek.com",
        "ZEBRA_MODEL_MAX_RETRIES": "0",
        "ZEBRA_RUNTIME_BUNDLE_CONFIG": "/e1/catalog.json",
        "ZEBRA_PUBLICATION_MANAGEMENT_CONFIG": "/e1/publication.json",
        "ZEBRA_E2E_MODEL_API_KEY": "synthetic-only",
        "ZEBRA_RABBIT_PUBLISH_ENABLED": "true",
        "ZEBRA_RABBIT_CONSUME_ENABLED": "true",
        "ZEBRA_RABBIT_RELAY_URL": (
            f"amqp://zebra-relay:{rabbit['ZEBRA_RABBIT_RELAY_PASSWORD']}@127.0.0.1:25672/%2Fzebra"
        ),
        "ZEBRA_RABBIT_CONSUMER_URL": (
            f"amqp://zebra-consumer:{rabbit['ZEBRA_RABBIT_CONSUMER_PASSWORD']}"
            "@127.0.0.1:25672/%2Fzebra"
        ),
        "ZEBRA_RABBIT_SHADOW_CONSUMER_URL": (
            f"amqp://zebra-shadow-consumer:{rabbit['ZEBRA_RABBIT_SHADOW_CONSUMER_PASSWORD']}"
            "@127.0.0.1:25672/%2Fzebra"
        ),
        "ZEBRA_COMMAND_EXECUTION_SLOTS": "4",
        "ZEBRA_COMMAND_SCOPED_ROLLOUT_ENABLED": "true",
        "SSL_CERT_FILE": "/e1/ca.crt",
        "AWS_CA_BUNDLE": "/e1/ca.crt",
    }
    private(root / "app.env", "\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    broker = {
        "ZEBRA_GRANT_BROKER_AUTHORITY_MODE": "generic",
        "ZEBRA_GRANT_BROKER_AUTHORITY_URL": "https://127.0.0.1:28444/authority",
        "ZEBRA_GRANT_BROKER_ISSUER": "https://127.0.0.1:28444",
        "ZEBRA_GRANT_BROKER_ORIGIN": "https://ha-e1.invalid",
        "ZEBRA_GRANT_BROKER_HOST_APP_ID": "ha-e1",
        "ZEBRA_GRANT_BROKER_NAMESPACE_ID": namespace,
        "ZEBRA_GRANT_BROKER_ALLOWED_SCOPES": "agent.run,event.read,artifact.read,artifact.publish",
        "ZEBRA_GRANT_BROKER_PRIVATE_KEY_FILE": "/secrets/broker.key",
        "SSL_CERT_FILE": "/e1/ca.crt",
    }
    private(root / "broker.env", "\n".join(f"{k}={v}" for k, v in broker.items()) + "\n")
    private(
        root / "init.sql",
        f"CREATE ROLE ha_app LOGIN NOSUPERUSER PASSWORD '{values['pg_app']}';\n"
        "ALTER DATABASE ha_e1 OWNER TO ha_app;\n",
    )
    for name in (
        "compose.yml",
        "Node.Caddyfile",
        "Control.Caddyfile",
        "verify.py",
        "check_model.py",
        "check_wire.py",
        "metering.py",
        "worker.py",
        "e1_composition.py",
        "prepare_execution.py",
        "check_composition.py",
        "prepare.py",
        "authority.py",
        "model.py",
        "initialize.py",
        "rabbitmq.conf",
    ):
        shutil.copyfile(Path(__file__).with_name(name), root / name)
    shutil.copyfile(
        Path(__file__).parents[1] / "cloud_effect_composition/fake_model.py", root / "fake_model.py"
    )
    repository = Path(__file__).resolve().parents[3]
    shutil.copyfile(
        repository / "docs/contracts/runtime-bundle-v1/example-envelope.json",
        root / "example-envelope.json",
    )
    shutil.copyfile(repository / "docker/rabbitmq/enabled_plugins", root / "enabled_plugins")
    shutil.copyfile(repository / "scripts/provision_rabbitmq.py", root / "provision_rabbitmq.py")
    print("Private synthetic E1 files prepared; no services started.")


if __name__ == "__main__":
    main()
