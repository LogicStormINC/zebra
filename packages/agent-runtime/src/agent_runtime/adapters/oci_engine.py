"""Pin CLI routing once; never re-resolve mutable ambient context during cleanup."""

import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess, run
from typing import Any
from urllib.parse import urlsplit

from agent_core.ports.runtime import RuntimeCapabilityError


class PinnedOciEngine:
    """Explicit Docker host / Podman URL with a credential-free configuration digest.

    ponytail: SSH aliases and implicit local Podman stores are ambiguous here;
    configure an explicit unix/tcp endpoint. Remote SSH pinning needs its own
    verified host/config contract rather than treating a mutable alias as identity.
    """

    def __init__(
        self,
        engine: str,
        *,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., CompletedProcess[str]] = run,
    ) -> None:
        self._env = dict(os.environ if env is None else env)
        self._runner = runner
        executable = shutil.which(engine, path=self._env.get("PATH"))
        if executable is None or Path(engine).name not in ("docker", "podman"):
            raise RuntimeCapabilityError("cloud runtime requires a resolvable Docker/Podman engine")
        self._engine, self._executable = engine, executable
        self._files: dict[str, str] = {}
        flags: list[str] = []
        if Path(engine).name == "docker":
            endpoint = self._env.get("DOCKER_HOST")
            # Docker context overrides DOCKER_HOST; resolve that selection exactly once.
            context = self._env.get("DOCKER_CONTEXT")
            if context or not endpoint:
                args = (
                    (executable, "context", "inspect", context)
                    if context
                    else (executable, "context", "inspect")
                )
                result = runner(
                    args, env=self._env, capture_output=True, text=True, check=False, timeout=10
                )
                try:
                    row = json.loads(result.stdout)[0]
                    endpoint = row["Endpoints"]["docker"]["Host"]
                    explicit_tls = self._env.get("DOCKER_CERT_PATH") and (
                        self._env.get("DOCKER_TLS_VERIFY") or self._env.get("DOCKER_TLS")
                    )
                    if result.returncode or (
                        row.get("TLSMaterial", {}).get("docker") and not explicit_tls
                    ):
                        raise ValueError("context TLS must be explicitly configured")
                except (KeyError, ValueError, TypeError, IndexError):
                    raise RuntimeCapabilityError(
                        "cloud Docker context must resolve an endpoint; configure TLS explicitly"
                    ) from None
            flags.extend(("--host", endpoint or ""))
            if self._env.get("DOCKER_TLS_VERIFY") or self._env.get("DOCKER_TLS"):
                cert_root = self._env.get("DOCKER_CERT_PATH")
                if not cert_root:
                    raise RuntimeCapabilityError(
                        "cloud Docker TLS requires explicit certificate paths"
                    )
                flags.append("--tlsverify" if self._env.get("DOCKER_TLS_VERIFY") else "--tls")
                for name, option in (("ca.pem", "--tlscacert"), ("cert.pem", "--tlscert")):
                    path = str((Path(cert_root) / name).resolve(strict=True))
                    self._files[path] = sha256(Path(path).read_bytes()).hexdigest()
                    flags.extend((option, path))
                flags.extend(("--tlskey", str((Path(cert_root) / "key.pem").resolve(strict=True))))
            # Omit disabled TLS flags: Docker treats explicit tlsverify=false as
            # a TLS option and still loads certificate files. Ambient TLS is cleared below.
        else:
            if self._env.get("CONTAINER_CONNECTION"):
                raise RuntimeCapabilityError(
                    "cloud Podman requires an explicit endpoint without a connection selector"
                )
            endpoint = self._env.get("CONTAINER_HOST")
            flags.extend(("--remote=true", "--url", endpoint or ""))
        parsed = urlsplit(endpoint or "")
        if (
            parsed.scheme not in ("unix", "tcp")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "unix" and (parsed.netloc or not parsed.path.startswith("/")))
            or (parsed.scheme == "tcp" and (not parsed.hostname or not parsed.port))
        ):
            raise RuntimeCapabilityError(
                "cloud engine requires an explicit credential-free unix/tcp endpoint"
            )
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "CONTAINER_HOST",
            "CONTAINER_CONNECTION",
            "CONTAINER_SSHKEY",
            "PODMAN_CONNECTIONS_CONF",
        ):
            self._env.pop(key, None)
        self._prefix = (executable, *flags)
        self._daemon_id = self._read_daemon_id() if Path(engine).name == "docker" else None
        self.identity = sha256(
            json.dumps(
                {"command": self._prefix, "certificates": self._files, "daemon": self._daemon_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def __call__(self, command: Sequence[str], **kwargs: Any) -> CompletedProcess[str]:
        if not command or command[0] != self._engine:
            raise RuntimeCapabilityError("runtime engine command changed after pinning")
        if any(
            sha256(Path(path).read_bytes()).hexdigest() != digest
            for path, digest in self._files.items()
        ):
            raise RuntimeCapabilityError("runtime engine TLS identity changed after pinning")
        if self._daemon_id is not None and self._read_daemon_id() != self._daemon_id:
            raise RuntimeCapabilityError("runtime engine daemon identity changed after pinning")
        return self._runner((*self._prefix, *command[1:]), env=self._env, **kwargs)

    def _read_daemon_id(self) -> str:
        result = self._runner(
            (*self._prefix, "info", "--format", "{{.ID}}"),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode or not result.stdout.strip():
            raise RuntimeCapabilityError("cloud Docker daemon identity is unavailable")
        return result.stdout.strip()
