"""Complete only the dedicated QA endpoints after protected dependency preparation."""

import json
import subprocess
from pathlib import Path as Path

from prepare_full_capability_qa import NETWORK, PREFIX, ROOT, capture, run


def main():
    record = json.loads((ROOT / "inventory.json").read_text())
    if record["prefix"] != PREFIX or record["worker_started"] is not False:
        raise ValueError("dedicated unexecuted QA stack required")
    with (ROOT / "seed.log").open("x") as log:
        run(
            "docker",
            "run",
            "--rm",
            "--network",
            NETWORK,
            "--user",
            "0",
            "--env-file",
            str(ROOT / "native.env"),
            "-v",
            str(ROOT) + ":/evidence",
            "-v",
            str(ROOT / "tls") + ":/qa:ro",
            "-v",
            str(ROOT / "deploy") + ":/operator:ro",
            "-e",
            "PYTHONPATH="
            + capture(
                "docker",
                "image",
                "inspect",
                record["native_image"],
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
            )
            .split("PYTHONPATH=", 1)[1]
            .splitlines()[0]
            + ":/operator",
            "--entrypoint",
            "python",
            record["native_image"],
            "/operator/seed_full_capability.py",
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    profile = json.loads((ROOT / "frontend-profile.json").read_text())
    (ROOT / "tls/frontend-profile.json").write_text(json.dumps(profile))
    settings = json.loads((ROOT / "site.json").read_text())
    settings["zebra_agent"]["jwks_file"] = "/qa/jwks.json"
    settings["zebra_agent"]["runtimes"]["cloud114"]["frontend_profile"] = profile
    (ROOT / "site.json").write_text(json.dumps(settings))
    run(
        "docker",
        "cp",
        str(ROOT / "site.json"),
        PREFIX + "-host:/home/frappe/frappe-bench/sites/capability-qa.local/site_config.json",
    )
    run(
        "docker",
        "exec",
        "--user",
        "0",
        PREFIX + "-host",
        "chown",
        "1000:1000",
        "/home/frappe/frappe-bench/sites/capability-qa.local/site_config.json",
    )
    run(
        "docker",
        "exec",
        PREFIX + "-host",
        "bench",
        "--site",
        "capability-qa.local",
        "clear-cache",
        stdout=subprocess.DEVNULL,
    )
    run("docker", "restart", PREFIX + "-host", stdout=subprocess.DEVNULL)
    run(
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0",
        "-v",
        str(ROOT / "mcp") + ":/mcp",
        "--entrypoint",
        "python",
        record["native_image"],
        "-c",
        "import os;os.chown('/mcp',65532,65532);os.chown('/mcp/master.json',65532,65532)",
    )
    env = (
        (ROOT / "native.env").read_text()
        + "ZEBRA_MCP_SECRET_ROOT=/mcp\nZEBRA_MCP_KEY_HANDLE=master\nZEBRA_MCP_KEY_VERSION=1\n"
    )
    (ROOT / "api.env").write_text(env)
    (ROOT / "api.env").chmod(0o600)
    run(
        "docker",
        "run",
        "-d",
        "--name",
        PREFIX + "-api",
        "--network",
        NETWORK,
        "--network-alias",
        "native-api",
        "--env-file",
        str(ROOT / "api.env"),
        "-v",
        str(ROOT / "tls") + ":/qa:ro",
        "-v",
        str(ROOT / "mcp") + ":/mcp:ro",
        "--entrypoint",
        "python",
        record["native_image"],
        "-m",
        "zebra_agent_api.server",
        stdout=subprocess.DEVNULL,
    )
    caddy = """https://erpnext-full-qa.zebra.local, https://127.0.0.1:18544 {
 tls /qa/server.crt /qa/server.key
 @manifest path /manifest
 handle @manifest {
  rewrite * /api/method/zebra_erpnext.gateway.manifest
  reverse_proxy host-backend:8000 {
   header_up X-Frappe-Site-Name capability-qa.local
  }
 }
 @invoke path /tools/*/invoke
 handle @invoke {
  rewrite * /api/method/zebra_erpnext.gateway.invoke
  reverse_proxy host-backend:8000 {
   header_up X-Frappe-Site-Name capability-qa.local
  }
 }
 handle /assets/* {
  reverse_proxy host-frontend:8080
 }
 handle {
  reverse_proxy host-backend:8000 {
   header_up X-Frappe-Site-Name capability-qa.local
  }
 }
}
https://agent-full-qa.zebra.local {
 tls /qa/server.crt /qa/server.key
 reverse_proxy native-api:8000
}
"""
    (ROOT / "Caddyfile").write_text(caddy)
    run(
        "docker",
        "run",
        "-d",
        "--name",
        PREFIX + "-frontend",
        "--network",
        NETWORK,
        "--network-alias",
        "host-frontend",
        "-v",
        record["sites"] + ":/home/frappe/frappe-bench/sites",
        "-e",
        "BACKEND=host-backend:8000",
        "-e",
        "SOCKETIO=host-backend:9000",
        "-e",
        "FRAPPE_SITE_NAME_HEADER=capability-qa.local",
        record["erp_image"],
        "nginx-entrypoint.sh",
        stdout=subprocess.DEVNULL,
    )
    # Both explicit listeners share the same mapped TLS port; no production route is edited.
    caddy = caddy.replace("https://127.0.0.1:18544", "https://127.0.0.1")
    (ROOT / "Caddyfile").write_text(caddy)
    image = capture(
        "docker",
        "inspect",
        "erpnext-dual-qa-authority-tls-c280841175cf-bindcap",
        "--format",
        "{{.Image}}",
    ).strip()
    run(
        "docker",
        "run",
        "-d",
        "--name",
        PREFIX + "-tls",
        "--network",
        NETWORK,
        "--network-alias",
        "erpnext-full-qa.zebra.local",
        "--network-alias",
        "agent-full-qa.zebra.local",
        "-p",
        "127.0.0.1:18544:443",
        "-v",
        str(ROOT / "tls") + ":/qa:ro",
        "-v",
        str(ROOT / "Caddyfile") + ":/etc/caddy/Caddyfile:ro",
        "-v",
        record["sites"] + ":/sites:ro",
        image,
        stdout=subprocess.DEVNULL,
    )
    print(
        json.dumps(
            dict(
                stage="qa_endpoints_started",
                worker_started=False,
                scheduler_started=False,
                model_calls=0,
                search_calls=0,
            )
        )
    )


if __name__ == "__main__":
    main()
