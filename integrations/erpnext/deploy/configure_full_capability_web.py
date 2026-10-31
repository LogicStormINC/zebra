"""Dedicated QA TLS over the unchanged controlled search backend; no query sent."""

import json
import subprocess
from pathlib import Path as Path

from prepare_full_capability_qa import NETWORK, PREFIX, ROOT


def main():
    state = json.loads((ROOT / "inventory.json").read_text())
    if state["prefix"] != PREFIX or state["worker_started"] is not False:
        raise ValueError("idle isolated QA stack required")
    source = json.loads(
        subprocess.check_output(
            ["docker", "inspect", "zebra-application-zebra-worker-1"], text=True
        )
    )[0]
    hosts = [
        v for v in source["HostConfig"].get("ExtraHosts", []) if v.startswith("search.zebra.test:")
    ]
    if hosts != ["search.zebra.test:192.168.160.1"]:
        raise ValueError("controlled route changed")
    name = PREFIX + "-search-tls"
    if (
        name
        in subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"], text=True
        ).splitlines()
    ):
        raise ValueError("owned search TLS candidate already exists; inspect retained evidence")
    tls = ROOT / "tls"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tls / "search.key"),
            "-out",
            str(tls / "search.crt"),
            "-days",
            "7",
            "-subj",
            "/CN=search-full-qa.zebra.local",
            "-addext",
            "subjectAltName=DNS:search-full-qa.zebra.local",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (tls / "search.key").chmod(0o600)
    # The existing search leaf expired Oct26. Keep that service untouched; an
    # isolated TLS listener retains its exact GET/path policy and backend.
    config = """{
 admin off
 auto_https disable_redirects
}
https://search-full-qa.zebra.local:18545 {
 bind 192.168.160.1
 tls /qa/search.crt /qa/search.key
 @search {
 method GET
 path /search /healthz
 }
 handle @search {
 reverse_proxy 127.0.0.1:18446
 }
 handle {
 respond 404
 }
 log {
 output discard
 }
}
"""
    (ROOT / "search-Caddyfile").write_text(config)
    image = json.loads(
        subprocess.check_output(["docker", "inspect", "zebra-web-search-search-tls-1"], text=True)
    )[0]["Image"]
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "host",
            "-v",
            str(tls) + ":/qa:ro",
            "-v",
            str(ROOT / "search-Caddyfile") + ":/etc/caddy/Caddyfile:ro",
            image,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    (tls / "trust.pem").write_bytes(
        (tls / "server.crt").read_bytes() + b"\n" + (tls / "search.crt").read_bytes()
    )
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in (ROOT / "api.env").read_text().splitlines()
        if "=" in line
    }
    values.update(
        ZEBRA_WEB_SEARCH_ENDPOINT="https://search-full-qa.zebra.local:18545/search",
        ZEBRA_WEB_SEARCH_PRIVATE_BACKEND="true",
        SSL_CERT_FILE="/qa/trust.pem",
    )
    (ROOT / "api.env").write_text("".join(k + "=" + v + "\n" for k, v in values.items()))
    search_host = "search-full-qa.zebra.local:192.168.160.1"
    code = (
        "import ssl,socket,json; c=ssl.create_default_context(); s=c.wrap"
        "_socket(socket.create_connection(('search-full-qa.zebra.local',1"
        "8545),timeout=5),server_hostname='search-full-qa.zebra.local'); "
        "print(json.dumps(dict(tls_verified=True,http_requests=0,search_r"
        "equests=0)));s.close()"
    )
    result = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "zebra-dependencies",
            "--add-host",
            search_host,
            "--env-file",
            str(ROOT / "api.env"),
            "-v",
            str(tls) + ":/qa:ro",
            "--entrypoint",
            "python",
            state["native_image"],
            "-c",
            code,
        ],
        text=True,
    )
    proof = json.loads(result)
    subprocess.run(["docker", "rm", "-f", PREFIX + "-api"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            PREFIX + "-api",
            "--network",
            NETWORK,
            "--network-alias",
            "native-api",
            "--add-host",
            search_host,
            "--env-file",
            str(ROOT / "api.env"),
            "-v",
            str(tls) + ":/qa:ro",
            "-v",
            str(ROOT / "mcp") + ":/mcp:ro",
            "--entrypoint",
            "python",
            state["native_image"],
            "-m",
            "zebra_agent_api.server",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["docker", "network", "connect", "zebra-dependencies", PREFIX + "-api"], check=True
    )
    (ROOT / "web-gate.json").write_text(
        json.dumps(
            dict(
                stage="controlled_search_configuration",
                **proof,
                default_engine_unchanged=True,
                original_search_restarted=False,
                original_leaf_expired=True,
            ),
            indent=2,
        )
    )
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
