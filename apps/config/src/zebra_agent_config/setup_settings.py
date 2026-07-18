import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SetupDependencySettings:
    url: str
    sha256: str
    file_name: str


@dataclass(frozen=True)
class SetupSettings:
    enabled: bool = False
    command: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    dependencies: tuple[SetupDependencySettings, ...] = ()
    lockfiles: tuple[str, ...] = ()
    credential_env: str | None = None
    max_dependency_bytes: int = 128 * 1024 * 1024


def load_setup_settings(values: Mapping[str, str]) -> SetupSettings:
    enabled = _bool(values.get("ZEBRA_SETUP_ENABLED", ""), default=False)
    configured = any(
        values.get(key, "").strip()
        for key in (
            "ZEBRA_SETUP_COMMAND_JSON",
            "ZEBRA_SETUP_ALLOWED_DOMAINS",
            "ZEBRA_SETUP_DEPENDENCIES_JSON",
            "ZEBRA_SETUP_LOCKFILES",
            "ZEBRA_SETUP_CREDENTIAL_ENV",
        )
    )
    if not enabled:
        if configured:
            raise ValueError("setup configuration requires ZEBRA_SETUP_ENABLED=true")
        return SetupSettings()
    command = _string_list(values, "ZEBRA_SETUP_COMMAND_JSON", json_required=True)
    allowed_domains = _csv(values, "ZEBRA_SETUP_ALLOWED_DOMAINS")
    lockfiles = _csv(values, "ZEBRA_SETUP_LOCKFILES")
    dependencies = _dependencies(values)
    if not command or not allowed_domains or not lockfiles or not dependencies:
        raise ValueError("enabled setup requires command, domains, dependencies, and lockfiles")
    credential_env = values.get("ZEBRA_SETUP_CREDENTIAL_ENV", "").strip() or None
    if credential_env and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", credential_env):
        raise ValueError("ZEBRA_SETUP_CREDENTIAL_ENV must be an environment variable name")
    max_bytes = _positive_int(
        values.get("ZEBRA_SETUP_MAX_DEPENDENCY_BYTES", ""),
        default=128 * 1024 * 1024,
    )
    return SetupSettings(
        enabled=True,
        command=command,
        allowed_domains=allowed_domains,
        dependencies=dependencies,
        lockfiles=lockfiles,
        credential_env=credential_env,
        max_dependency_bytes=max_bytes,
    )


def _dependencies(values: Mapping[str, str]) -> tuple[SetupDependencySettings, ...]:
    raw = values.get("ZEBRA_SETUP_DEPENDENCIES_JSON", "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("ZEBRA_SETUP_DEPENDENCIES_JSON must be valid JSON") from exc
    if not isinstance(payload, list) or not 1 <= len(payload) <= 64:
        raise ValueError("ZEBRA_SETUP_DEPENDENCIES_JSON must contain 1 to 64 entries")
    dependencies: list[SetupDependencySettings] = []
    for entry in payload:
        if not isinstance(entry, dict) or set(entry) != {"url", "sha256", "file_name"}:
            raise ValueError("setup dependencies require url, sha256, and file_name")
        url, digest, file_name = (entry[key] for key in ("url", "sha256", "file_name"))
        if not all(isinstance(value, str) and value.strip() for value in (url, digest, file_name)):
            raise ValueError("setup dependency fields must be non-blank strings")
        normalized_name = file_name.strip()
        if Path(normalized_name).name != normalized_name:
            raise ValueError("setup dependency file_name must be a plain file name")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest.strip()):
            raise ValueError("setup dependency sha256 must be a digest")
        dependencies.append(
            SetupDependencySettings(
                url=url.strip(),
                sha256=digest.strip().lower(),
                file_name=normalized_name,
            )
        )
    return tuple(dependencies)


def _string_list(
    values: Mapping[str, str],
    key: str,
    *,
    json_required: bool,
) -> tuple[str, ...]:
    raw = values.get(key, "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{key} must be valid JSON") from exc
    if json_required and (
        not isinstance(payload, list)
        or not 1 <= len(payload) <= 32
        or any(not isinstance(item, str) or not item.strip() for item in payload)
    ):
        raise ValueError(f"{key} must be a list of 1 to 32 non-blank strings")
    return tuple(item.strip() for item in payload)


def _csv(values: Mapping[str, str], key: str) -> tuple[str, ...]:
    raw = values.get(key, "").strip()
    return tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))


def _positive_int(raw: str, *, default: int) -> int:
    try:
        value = int(raw.strip() or default)
    except ValueError as exc:
        raise ValueError("ZEBRA_SETUP_MAX_DEPENDENCY_BYTES must be an integer") from exc
    if value <= 0:
        raise ValueError("ZEBRA_SETUP_MAX_DEPENDENCY_BYTES must be positive")
    return value


def _bool(raw: str, *, default: bool) -> bool:
    normalized = raw.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("ZEBRA_SETUP_ENABLED must be a boolean")
