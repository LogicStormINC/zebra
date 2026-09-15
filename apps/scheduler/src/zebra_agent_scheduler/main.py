"""Command-line process for durable user Schedule materialization."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from threading import Event

import httpx
from agent_core.application import TaskScheduleMaterializer
from agent_integrations import HttpScheduleAuthorityRevalidator
from agent_security import CachingJwksKeyResolver, PyJwtHostGrantDecoder
from agent_storage import (
    PostgresTaskScheduleFiringStore,
    PostgresTaskScheduleStore,
    cloud_composition_from_environment,
)
from zebra_agent_api import create_app
from zebra_agent_api.extension_composition import (
    compose_http_extensions,
    compose_http_turn_admission,
    resolve_publication_cloud,
)
from zebra_agent_config import load_settings

from zebra_agent_scheduler.admission import ZebraApiScheduledTaskAdmission
from zebra_agent_scheduler.config import load_scheduler_settings


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    settings = load_settings()
    if settings.deployment != "cloud" or settings.storage_authority != "postgresql":
        raise ValueError("user Schedule materialization requires cloud PostgreSQL authority")
    scheduler = load_scheduler_settings()
    cloud = resolve_publication_cloud(
        settings, None, cloud_composition_from_environment(), None, None
    )
    assert cloud is not None
    api = create_app(settings=settings, cloud_composition=cloud)
    extension_store, _, _, _ = compose_http_extensions(
        settings,
        api,
        cloud_composition=cloud,
        extension_store=None,
        service=None,
    )
    extension_admission = compose_http_turn_admission(
        settings, api, extension_store, cloud_composition=cloud
    )
    stop = Event()
    _install_signal_handlers(stop)
    with httpx.Client() as client:
        materializer = TaskScheduleMaterializer(
            schedules=PostgresTaskScheduleStore(
                cloud.dsn, deployment_namespace=cloud.deployment_namespace
            ),
            firings=PostgresTaskScheduleFiringStore(
                cloud.dsn, deployment_namespace=cloud.deployment_namespace
            ),
            authority=HttpScheduleAuthorityRevalidator(
                scheduler.grant_exchange,
                PyJwtHostGrantDecoder(CachingJwksKeyResolver()),
                client=client,
            ),
            admission=ZebraApiScheduledTaskAdmission(api, extension_admission=extension_admission),
            claimant=scheduler.claimant,
            batch_size=scheduler.batch_size,
            claim_ttl_seconds=scheduler.claim_ttl_seconds,
            max_attempts=scheduler.max_attempts,
        )
        cycles = _run(materializer, stop, once=args.once, poll_seconds=scheduler.poll_seconds)
    print(json.dumps({"status": "stopped", "cycles": cycles}, sort_keys=True))
    return 0


def _run(
    materializer: TaskScheduleMaterializer,
    stop: Event,
    *,
    once: bool,
    poll_seconds: float,
) -> int:
    cycles = 0
    while not stop.is_set():
        result = materializer.run_once()
        cycles += 1
        if result.claimed:
            print(json.dumps(result.__dict__, sort_keys=True), flush=True)
        if once:
            break
        stop.wait(poll_seconds)
    return cycles


def _install_signal_handlers(stop: Event) -> None:
    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zebra-agent-scheduler")
    parser.add_argument("--once", action="store_true", help="Materialize one bounded batch")
    return parser


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
