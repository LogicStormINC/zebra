"""Run on the authorized host. Keeps credentials in protected local files."""

import json
import os as os
import secrets
import subprocess
from pathlib import Path

ROOT = Path("/opt/erpnext/zebra-agent")
SECRET = ROOT / "secrets"


def command(*args, **kwargs):
    return subprocess.check_output(args, **kwargs)


def private(path, value):
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(value)


def prepare():
    containers = json.loads(
        command(
            "docker", "inspect", "zebra-application-zebra-api-1", "zebra-application-zebra-worker-1"
        )
    )
    key = SECRET / "signing.pem"
    if not key.exists():
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(key),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        key.chmod(0o600)
    script = (
        "import sys,json,base64\nfrom cryptography.hazmat.primitives.seria"
        "lization import load_pem_private_key\nn=load_pem_private_key(sys."
        "stdin.buffer.read(),None).public_key().public_numbers()\ndef b(x)"
        ":return base64.urlsafe_b64encode(x.to_bytes((x.bit_length()+7)//"
        "8,'big')).rstrip(b'=').decode()\nprint(json.dumps({'keys':[{'kty'"
        ":'RSA','kid':'erpnext-v1','use':'sig','alg':'RS256','n':b(n.n),'"
        "e':b(n.e)}]}))\n"
    )
    jwks = command(
        "docker",
        "exec",
        "-i",
        "zebra-application-zebra-api-1",
        "python",
        "-c",
        script,
        input=key.read_bytes(),
    ).decode()
    private(SECRET / "jwks.json", jwks)
    ca = command(
        "docker",
        "exec",
        "zebra-application-zebra-api-1",
        "cat",
        "/etc/ssl/certs/ca-certificates.crt",
    )
    ca += Path("/opt/caddy/data/caddy/pki/authorities/local/root.crt").read_bytes()
    (SECRET / "ca.crt").write_bytes(ca)
    (SECRET / "ca.crt").chmod(0o644)
    saved = SECRET / "host-settings.json"
    settings = (
        json.loads(saved.read_text())
        if saved.exists()
        else dict(
            enabled=True,
            base_url="https://erpnext-agent.zebra.local",
            issuer="https://erpnext.zebra.local",
            origin="https://192.168.110.42:18443",
            signing_key="/run/zebra/signing.pem",
            jwks_file="/run/zebra/jwks.json",
            ca_file="/run/zebra/ca.crt",
            host_secret=secrets.token_urlsafe(40),
            model_profile="deepseek-v4-flash-executor-v1",
        )
    )
    private(saved, json.dumps(settings))
    services = {}
    for old, role in zip(containers, ("api", "worker"), strict=False):
        env = dict(item.split("=", 1) for item in old["Config"]["Env"])
        env.update(
            ZEBRA_DEPLOYMENT_NAMESPACE="erpnext",
            ZEBRA_AUTHORITY_ISSUER=settings["issuer"],
            ZEBRA_HISTORY_SCOPE_NAMESPACE="erpnext-history",
            ZEBRA_CONTINUATION_SCOPE_NAMESPACE="erpnext-continuation",
            ZEBRA_WORKSPACE_VOLUME_ROOT="/var/lib/zebra/erpnext-workspaces",
            ZEBRA_S3_KEY_PREFIX="erpnext/artifacts/v1",
            ZEBRA_HOST_TOOL_ENDPOINT=settings["issuer"],
            ZEBRA_HOST_TOOL_WORKLOAD_IDENTITY="erpnext-worker",
            ZEBRA_HOST_TOOL_SHARED_SECRET=settings["host_secret"],
            ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES="erpnext.zebra.local",
            ZEBRA_CLIENT_INTEGRATION_ENABLED="true",
            SSL_CERT_FILE="/run/zebra/ca.crt",
            REQUESTS_CA_BUNDLE="/run/zebra/ca.crt",
        )
        volumes = []
        for mount in old["Mounts"]:
            if mount["Destination"] == "/var/lib/zebra/workspaces":
                volumes.append(
                    "/var/lib/zebra/erpnext-workspaces:/var/lib/zebra/erpnext-workspaces"
                )
            elif mount["Destination"] not in {"/run/zebra/ca.crt"}:
                volumes.append(
                    f"{mount['Source']}:{mount['Destination']}" + (":ro" if not mount["RW"] else "")
                )
        volumes.append(f"{SECRET}/ca.crt:/run/zebra/ca.crt:ro")
        service = dict(
            image=old["Image"],
            restart="unless-stopped",
            environment=env,
            volumes=volumes,
            networks=["zebra-dependencies"],
            extra_hosts={
                "erpnext.zebra.local": "192.168.110.42",
                "erpnext-agent.zebra.local": "192.168.110.42",
            },
        )
        if old["Config"].get("Entrypoint"):
            service["entrypoint"] = old["Config"]["Entrypoint"]
        if role == "api":
            service["ports"] = ["127.0.0.1:18082:8000"]
            if old["Config"].get("Cmd"):
                service["command"] = old["Config"]["Cmd"]
        else:
            service["command"] = ["--worker-id", "erpnext-worker", "--idle-sleep-seconds", "0.25"]
        services[role] = service
    private(
        ROOT / "compose.json",
        json.dumps(
            dict(
                name="erpnext-agent",
                services=services,
                networks={"zebra-dependencies": {"external": True}},
                volumes={"erpnext-agent-workspaces": {}},
            ),
            indent=2,
        ),
    )
    override = {
        "services": {
            role: {"image": "erpnext:zebra-20261023"}
            for role in (
                "backend",
                "frontend",
                "configurator",
                "websocket",
                "queue-short",
                "queue-long",
                "scheduler",
            )
        }
    }
    override["services"]["backend"].update(
        volumes=[f"{SECRET}:/run/zebra:ro"],
        extra_hosts={"erpnext-agent.zebra.local": "192.168.110.42"},
    )
    (ROOT / "erpnext-override.json").write_text(json.dumps(override, indent=2))
    print(
        "Prepared isolated namespace, image-pinned services, protected signing/workload credentials"
    )


if __name__ == "__main__":
    prepare()
