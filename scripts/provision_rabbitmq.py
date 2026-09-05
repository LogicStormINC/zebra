"""Provision only an explicitly selected loopback development broker; never print secrets."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

ROUTES = {"trench": "ai.turn.ready", "zebra": "session.command.ready"}
BASE_PASSWORD_KEYS = ("RABBITMQ_ADMIN_PASSWORD",) + tuple(
    f"{system.upper()}_RABBIT_{role.upper()}_PASSWORD"
    for system in ROUTES
    for role in ("relay", "consumer")
)
SHADOW_PASSWORD_KEYS = tuple(
    f"{system.upper()}_RABBIT_SHADOW_CONSUMER_PASSWORD" for system in ROUTES
)
PASSWORD_KEYS = BASE_PASSWORD_KEYS + SHADOW_PASSWORD_KEYS
SOURCE_BASE_PASSWORD_KEYS = (
    "TRENCH_SOURCE_RABBIT_RELAY_PASSWORD",
    "TRENCH_SOURCE_RABBIT_CONSUMER_PASSWORD",
)
SOURCE_SHADOW_PASSWORD_KEYS = ("TRENCH_SOURCE_RABBIT_SHADOW_CONSUMER_PASSWORD",)
SOURCE_PASSWORD_KEYS = SOURCE_BASE_PASSWORD_KEYS + SOURCE_SHADOW_PASSWORD_KEYS


def prepare(path: Path, *, source_delivery: bool = False) -> None:
    """Create exclusively so repeated setup cannot rotate credentials accidentally."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        for key in PASSWORD_KEYS + (SOURCE_PASSWORD_KEYS if source_delivery else ()):
            output.write(f"{key}={secrets.token_urlsafe(32)}\n")
        output.write("RABBITMQ_AMQP_PORT=25672\nRABBITMQ_MANAGEMENT_PORT=25673\n")
        output.write("RABBITMQ_METRICS_PORT=25692\n")


def read_settings(path: Path) -> dict[str, str]:
    if path.stat().st_mode & 0o077:
        raise ValueError("RabbitMQ settings file must be private (chmod 600)")
    settings = dict(line.split("=", 1) for line in path.read_text().splitlines() if line)
    for key in BASE_PASSWORD_KEYS:
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", settings.get(key, "")):
            raise ValueError("missing or invalid RabbitMQ development credential")
    shadow_present = tuple(bool(settings.get(key)) for key in SHADOW_PASSWORD_KEYS)
    if any(shadow_present) and not all(shadow_present):
        raise ValueError("shadow consumer credentials must be configured as a set")
    for key in SHADOW_PASSWORD_KEYS if all(shadow_present) else ():
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", settings[key]):
            raise ValueError("missing or invalid RabbitMQ development credential")
    source_base_present = tuple(bool(settings.get(key)) for key in SOURCE_BASE_PASSWORD_KEYS)
    if any(source_base_present) and not all(source_base_present):
        raise ValueError("source delivery credentials must be configured as a set")
    source_shadow_present = bool(settings.get(SOURCE_SHADOW_PASSWORD_KEYS[0]))
    if source_shadow_present and not all(source_base_present):
        raise ValueError("source shadow credential requires source delivery credentials")
    for key in SOURCE_BASE_PASSWORD_KEYS if all(source_base_present) else ():
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", settings[key]):
            raise ValueError("missing or invalid RabbitMQ development credential")
    if source_shadow_present and not re.fullmatch(
        r"[A-Za-z0-9_-]{32,128}", settings[SOURCE_SHADOW_PASSWORD_KEYS[0]]
    ):
        raise ValueError("missing or invalid RabbitMQ development credential")
    for key in ("RABBITMQ_AMQP_PORT", "RABBITMQ_MANAGEMENT_PORT", "RABBITMQ_METRICS_PORT"):
        if not settings.get(key, "").isdigit() or not 1024 <= int(settings[key]) <= 65535:
            raise ValueError("invalid explicit local port")
    return settings


def _append_credentials(path: Path, keys: tuple[str, ...]) -> None:
    original = path.read_bytes()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            output.write(original)
            if original and not original.endswith(b"\n"):
                output.write(b"\n")
            for key in keys:
                output.write(f"{key}={secrets.token_urlsafe(32)}\n".encode())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def prepare_source(path: Path) -> None:
    """Atomically add source credentials without rotating existing settings."""
    settings = read_settings(path)
    if any(key in settings for key in SOURCE_PASSWORD_KEYS):
        raise ValueError("source delivery credentials already exist")
    _append_credentials(path, SOURCE_PASSWORD_KEYS)


def prepare_shadow(path: Path) -> None:
    """Atomically upgrade a legacy settings file with independent shadow identities."""
    settings = read_settings(path)
    if any(key in settings for key in SHADOW_PASSWORD_KEYS):
        raise ValueError("shadow consumer credentials already exist")
    keys = SHADOW_PASSWORD_KEYS
    if all(settings.get(key) for key in SOURCE_BASE_PASSWORD_KEYS):
        if any(key in settings for key in SOURCE_SHADOW_PASSWORD_KEYS):
            raise ValueError("source shadow consumer credential already exists")
        keys += SOURCE_SHADOW_PASSWORD_KEYS
    _append_credentials(path, keys)


def topology(system: str) -> dict[str, Any]:
    """No user payloads or secrets in static topology. Provisioner alone reads DLQs."""
    route = ROUTES[system]
    queue = f"{system}.{route}.q"
    return {
        "vhost": f"/{system}",
        "exchange": f"{system}.command.x",
        "shadow_exchange": f"{system}.command.shadow.x",
        "dlx": f"{system}.command.dlx",
        "queue": queue,
        "dlq": f"{system}.{route}.dlq",
        "routing_key": f"{route}.v1",
        "shadow_queue": f"{system}.{route}.shadow.q",
        "shadow_routing_key": f"{route}.shadow.v1",
        "diagnostic_exchange": f"{system}.command.diagnostic.x",
        "diagnostic_queue": f"{system}.command.diagnostic.q",
        "diagnostic_routing_key": "delivery.rejected.v1",
    }


def source_topology() -> dict[str, str]:
    return {
        "vhost": "/trench",
        "exchange": "trench.command.x",
        "shadow_exchange": "trench.command.shadow.x",
        "dlx": "trench.command.dlx",
        "queue": "trench.source.fetch.ready.q",
        "dlq": "trench.source.fetch.ready.dlq",
        "routing_key": "source.fetch.ready.v1",
        "shadow_queue": "trench.source.fetch.ready.shadow.q",
        "shadow_routing_key": "source.fetch.ready.shadow.v1",
        "diagnostic_exchange": "trench.command.diagnostic.x",
        "diagnostic_routing_key": "delivery.rejected.v1",
    }


def provision(settings: dict[str, str], *, source_delivery: bool = False) -> None:
    # ponytail: local-only bootstrap. Production provisioning belongs to TLS/IaC tooling.
    if source_delivery and not all(settings.get(key) for key in SOURCE_BASE_PASSWORD_KEYS):
        raise ValueError("source delivery credentials are not configured")
    base = f"http://127.0.0.1:{settings['RABBITMQ_MANAGEMENT_PORT']}/api/"
    with httpx.Client(
        base_url=base,
        auth=("provisioner", settings["RABBITMQ_ADMIN_PASSWORD"]),
        timeout=10,
        trust_env=False,
    ) as client:

        def put(path: str, body: dict[str, Any]) -> None:
            response = client.put(path, json=body)
            if response.status_code not in (201, 204):
                raise RuntimeError(f"RabbitMQ provisioning rejected (HTTP {response.status_code})")

        for system in ROUTES:
            spec = topology(system)
            vhost = quote(spec["vhost"], safe="")
            put(f"vhosts/{vhost}", {"default_queue_type": "quorum"})
            put(f"vhost-limits/{vhost}/max-connections", {"value": 32})
            put(f"vhost-limits/{vhost}/max-queues", {"value": 8})
            put(
                f"permissions/{vhost}/provisioner",
                {
                    "configure": ".*",
                    "write": ".*",
                    "read": ".*",
                },
            )
            for exchange in (
                spec["exchange"],
                spec["shadow_exchange"],
                spec["dlx"],
                spec["diagnostic_exchange"],
            ):
                put(f"exchanges/{vhost}/{exchange}", {"type": "topic", "durable": True})
            for name in (
                spec["queue"],
                spec["shadow_queue"],
                spec["dlq"],
                spec["diagnostic_queue"],
            ):
                put(
                    f"queues/{vhost}/{name}",
                    {
                        "durable": True,
                        "arguments": {"x-queue-type": "quorum"},
                    },
                )
            bindings = (
                (spec["exchange"], spec["queue"], spec["routing_key"]),
                (
                    spec["shadow_exchange"],
                    spec["shadow_queue"],
                    spec["shadow_routing_key"],
                ),
                (spec["dlx"], spec["dlq"], spec["dlq"]),
                (
                    spec["diagnostic_exchange"],
                    spec["diagnostic_queue"],
                    spec["diagnostic_routing_key"],
                ),
            )
            for exchange, queue, key in bindings:
                response = client.post(
                    f"bindings/{vhost}/e/{exchange}/q/{queue}", json={"routing_key": key}
                )
                if response.status_code != 201:
                    raise RuntimeError("RabbitMQ binding creation rejected")
            put(
                f"policies/{vhost}/ready-reliability",
                {
                    "pattern": f"^{re.escape(spec['queue'])}$",
                    "apply-to": "quorum_queues",
                    "priority": 10,
                    "definition": {
                        "dead-letter-exchange": spec["dlx"],
                        "dead-letter-routing-key": spec["dlq"],
                        "dead-letter-strategy": "at-least-once",
                        "overflow": "reject-publish",
                        "delivery-limit": 5,
                        "max-length-bytes": 4_194_304,
                    },
                },
            )
            put(
                f"policies/{vhost}/bounded-shadow",
                {
                    "pattern": f"^{re.escape(spec['shadow_queue'])}$",
                    "apply-to": "quorum_queues",
                    "priority": 10,
                    "definition": {
                        "overflow": "reject-publish",
                        "max-length-bytes": 1_048_576,
                        "message-ttl": 86_400_000,
                    },
                },
            )
            put(
                f"policies/{vhost}/restricted-quarantine",
                {
                    "pattern": f"^{re.escape(spec['dlq'])}$",
                    "apply-to": "quorum_queues",
                    "priority": 10,
                    "definition": {
                        "overflow": "reject-publish",
                        "max-length-bytes": 1_048_576,
                        "message-ttl": 86_400_000,
                    },
                },
            )
            put(
                f"policies/{vhost}/safe-diagnostic",
                {
                    "pattern": f"^{re.escape(spec['diagnostic_queue'])}$",
                    "apply-to": "quorum_queues",
                    "priority": 10,
                    "definition": {
                        "overflow": "reject-publish",
                        "max-length-bytes": 4_194_304,
                        "message-ttl": 604_800_000,
                    },
                },
            )
            roles = ["relay", "consumer"]
            if settings.get(f"{system.upper()}_RABBIT_SHADOW_CONSUMER_PASSWORD"):
                roles.append("shadow_consumer")
            for role in roles:
                user = f"{system}-{role.replace('_', '-')}"
                put(
                    f"users/{user}",
                    {
                        "password": settings[f"{system.upper()}_RABBIT_{role.upper()}_PASSWORD"],
                        "tags": [],
                    },
                )
                put(
                    f"permissions/{vhost}/{user}",
                    {
                        "configure": "^$",
                        "write": (
                            f"^({re.escape(spec['exchange'])}|"
                            f"{re.escape(spec['shadow_exchange'])}|"
                            f"{re.escape(spec['diagnostic_exchange'])})$"
                        )
                        if role == "relay"
                        else "^$",
                        "read": (
                            f"^{re.escape(spec['queue'])}$"
                            if role == "consumer"
                            else f"^{re.escape(spec['shadow_queue'])}$"
                            if role == "shadow_consumer"
                            else "^$"
                        ),
                    },
                )
                if role == "relay":
                    put(
                        f"topic-permissions/{vhost}/{user}",
                        {
                            "exchange": spec["shadow_exchange"],
                            "write": f"^{re.escape(spec['shadow_routing_key'])}$",
                            "read": "^$",
                        },
                    )
                    put(
                        f"topic-permissions/{vhost}/{user}",
                        {
                            "exchange": spec["diagnostic_exchange"],
                            "write": f"^{re.escape(spec['diagnostic_routing_key'])}$",
                            "read": "^$",
                        },
                    )
                    put(
                        f"topic-permissions/{vhost}/{user}",
                        {
                            "exchange": spec["exchange"],
                            "write": f"^{re.escape(spec['routing_key'])}$",
                            "read": "^$",
                        },
                    )
                for limit, value in (("max-connections", 8), ("max-channels", 16)):
                    put(f"user-limits/{user}/{limit}", {"value": value})
        if source_delivery:
            spec = source_topology()
            vhost = quote(spec["vhost"], safe="")
            for name in (spec["queue"], spec["shadow_queue"], spec["dlq"]):
                put(
                    f"queues/{vhost}/{name}",
                    {"durable": True, "arguments": {"x-queue-type": "quorum"}},
                )
            for exchange, queue, key in (
                (spec["exchange"], spec["queue"], spec["routing_key"]),
                (
                    spec["shadow_exchange"],
                    spec["shadow_queue"],
                    spec["shadow_routing_key"],
                ),
                (spec["dlx"], spec["dlq"], spec["dlq"]),
            ):
                response = client.post(
                    f"bindings/{vhost}/e/{exchange}/q/{queue}", json={"routing_key": key}
                )
                if response.status_code != 201:
                    raise RuntimeError("RabbitMQ binding creation rejected")
            for name, queue, definition in (
                (
                    "source-bounded-shadow",
                    spec["shadow_queue"],
                    {
                        "overflow": "reject-publish",
                        "max-length-bytes": 1_048_576,
                        "message-ttl": 86_400_000,
                    },
                ),
                (
                    "source-ready-reliability",
                    spec["queue"],
                    {
                        "dead-letter-exchange": spec["dlx"],
                        "dead-letter-routing-key": spec["dlq"],
                        "dead-letter-strategy": "at-least-once",
                        "overflow": "reject-publish",
                        "delivery-limit": 5,
                        "max-length-bytes": 4_194_304,
                    },
                ),
                (
                    "source-restricted-quarantine",
                    spec["dlq"],
                    {
                        "overflow": "reject-publish",
                        "max-length-bytes": 1_048_576,
                        "message-ttl": 86_400_000,
                    },
                ),
            ):
                put(
                    f"policies/{vhost}/{name}",
                    {
                        "pattern": f"^{re.escape(queue)}$",
                        "apply-to": "quorum_queues",
                        "priority": 10,
                        "definition": definition,
                    },
                )
            roles = ["relay", "consumer"]
            if settings.get(SOURCE_SHADOW_PASSWORD_KEYS[0]):
                roles.append("shadow_consumer")
            for role in roles:
                user = f"trench-source-{role.replace('_', '-')}"
                put(
                    f"users/{user}",
                    {
                        "password": settings[f"TRENCH_SOURCE_RABBIT_{role.upper()}_PASSWORD"],
                        "tags": [],
                    },
                )
                put(
                    f"permissions/{vhost}/{user}",
                    {
                        "configure": "^$",
                        "write": (
                            f"^({re.escape(spec['exchange'])}|"
                            f"{re.escape(spec['shadow_exchange'])}|"
                            f"{re.escape(spec['diagnostic_exchange'])})$"
                            if role == "relay"
                            else "^$"
                        ),
                        "read": (
                            f"^{re.escape(spec['queue'])}$"
                            if role == "consumer"
                            else f"^{re.escape(spec['shadow_queue'])}$"
                            if role == "shadow_consumer"
                            else "^$"
                        ),
                    },
                )
                if role == "relay":
                    for exchange, route in (
                        (spec["exchange"], spec["routing_key"]),
                        (spec["shadow_exchange"], spec["shadow_routing_key"]),
                        (spec["diagnostic_exchange"], spec["diagnostic_routing_key"]),
                    ):
                        put(
                            f"topic-permissions/{vhost}/{user}",
                            {"exchange": exchange, "write": f"^{re.escape(route)}$", "read": "^$"},
                        )
                for limit, value in (("max-connections", 8), ("max-channels", 16)):
                    put(f"user-limits/{user}/{limit}", {"value": value})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "prepare-source", "prepare-shadow", "apply"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--source-delivery", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args.env_file, source_delivery=args.source_delivery)
        elif args.action == "prepare-source":
            prepare_source(args.env_file)
        elif args.action == "prepare-shadow":
            prepare_shadow(args.env_file)
        else:
            settings = read_settings(args.env_file)
            provision(settings, source_delivery=args.source_delivery)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError):
        raise SystemExit(
            "RabbitMQ setup failed; check private settings and local broker health"
        ) from None
    print(f"RabbitMQ {args.action} complete; business services remain unchanged")


if __name__ == "__main__":
    main()
