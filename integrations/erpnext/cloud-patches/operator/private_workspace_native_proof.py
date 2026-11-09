"""Confined immutable native-proof helper client and bounded cleanup."""

from __future__ import annotations

import json
import re
import socket
import subprocess
from pathlib import Path
from uuid import uuid4

from private_workspace_allocator import canonical, remaining, require_fresh, trusted


class NativeProof:
    def __init__(self, config):
        self.image = config["helper_image"]
        if (
            not isinstance(self.image, str)
            or re.fullmatch(r"(?:[a-zA-Z0-9./:_-]+@)?sha256:[0-9a-f]{64}", self.image) is None
        ):
            raise ValueError("immutable native helper image digest required")
        generation = config.get("generation", "native105")
        profiles = {
            "native105": (
                "erpnext-private-proof",
                "zebra_agent_worker.erp_private_workspace_proof",
            ),
            "cloud114": ("erpnext-full-proof", "full_workspace_proof"),
            "cloud114-qa": ("erpnext-full-qa-proof", "full_workspace_proof"),
        }
        if generation not in profiles:
            raise ValueError("unknown runtime generation")
        self.network, self.module = profiles[generation]
        self.qa = generation == "cloud114-qa"
        if config["helper_network"] != self.network:
            raise ValueError("dedicated proof network required")
        self.hostname = config.get("helper_hostname")
        if (
            not isinstance(self.hostname, str)
            or len(self.hostname) > 253
            or re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                self.hostname,
            )
            is None
            or self.hostname.rsplit(".", 1)[-1].isdecimal()
            or "localhost" in self.hostname.split(".")
        ):
            raise ValueError("single canonical helper FQDN required")
        try:
            socket.getaddrinfo(self.hostname, None, flags=socket.AI_NUMERICHOST)
        except socket.gaierror:
            pass
        else:
            raise ValueError("numeric helper hostname forbidden")
        self.failed_cleanup = False
        self.credentials = dict(
            readonly_dsn=config["readonly_dsn"],
            shared_secret=config["host_tool_shared_secret"],
            ca_pem=None,
        )
        if config.get("host_ca_file"):
            ca = Path(config["host_ca_file"])
            trusted(ca, directory=False)
            self.credentials["ca_pem"] = ca.read_text()

    def require_clean(self):
        names = subprocess.check_output(
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                "name=erp-private-proof-",
                "--format",
                "{{.Names}}",
            ],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        if any(name.startswith("erp-private-proof-") for name in names.splitlines()):
            raise ValueError("orphan proof helper requires operator cleanup")

    def __call__(self, session_id, workspace_id):
        if self.failed_cleanup:
            raise ValueError("proof helper cleanup requires operator review")
        nonce = str(uuid4())
        name = "erp-private-proof-" + nonce
        packet = canonical(
            dict(self.credentials, session_id=session_id, workspace_id=workspace_id, nonce=nonce)
        )
        if len(packet) > 16384:
            raise ValueError("bounded proof credentials required")
        argv = [
            "docker",
            "run",
            "--pull=never",
            "--interactive",
            "--name",
            name,
            "--network",
            self.network,
            "--env",
            "ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES=" + self.hostname,
            "--env",
            "ZEBRA_FULL_QA=" + str(self.qa).lower(),
            "--user",
            "65532:65532",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--entrypoint",
            "/app/.venv/bin/python",
            self.image,
            "-m",
            self.module,
        ]
        available = remaining()
        # ponytail: reserve 5s inside the 20s deadline; observed die-to-destroy was 3.798s.
        if available <= 5:
            raise TimeoutError("insufficient helper cleanup budget")
        try:
            output = subprocess.check_output(
                argv, input=packet, timeout=min(7, available - 5), stderr=subprocess.DEVNULL
            )
            if len(output) > 4096:
                raise ValueError("bounded proof response required")
            proof = json.loads(output)
            if (
                set(proof)
                != {"session_id", "workspace_id", "nonce", "identity", "state", "expires_at"}
                or proof["session_id"] != session_id
                or proof["workspace_id"] != workspace_id
                or proof["nonce"] != nonce
                or proof["state"] not in {"pending", "ready", "sealed"}
                or not isinstance(proof["identity"], str)
                or re.fullmatch("[0-9a-f]{64}", proof["identity"]) is None
            ):
                raise ValueError("native independent proof disagrees")
            require_fresh(proof["expires_at"])
            return proof["identity"], proof["state"], proof["expires_at"]
        finally:
            # Killing docker's client does not kill its container. Bounded forced cleanup
            # has a unique fixed prefix and never touches Worker or business containers.
            try:
                result = subprocess.run(
                    ["docker", "rm", "--force", name],
                    timeout=min(5, remaining()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode != 0:
                    raise ValueError("proof helper cleanup failed")
            except (OSError, subprocess.TimeoutExpired, TimeoutError, ValueError) as error:
                self.failed_cleanup = True
                raise ValueError("proof helper cleanup requires operator review") from error
