"""Independent Cloud cleanup consumer; no harness, model, or search execution."""

import argparse
import logging
import os
import time
from contextlib import nullcontext
from uuid import uuid4

from agent_runtime.command_runtime_cleanup import cleanup_runtime_batch
from agent_runtime.force_stop_cleanup import recover_force_stops
from agent_storage.postgres.connection_capacity import PROFILE_ENV, capacity_lane
from agent_storage.postgres.connection_pool import postgres_pool_scope
from agent_storage.postgres.database import PostgresDatabase
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_worker.runtime_factory import pin_cloud_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    if settings.deployment != "cloud" or settings.storage_authority != "postgresql":
        raise ValueError("cleanup service requires Cloud PostgreSQL composition")
    with (postgres_pool_scope(settings.database_url, component="cleanup")
          if os.environ.get(PROFILE_ENV) else nullcontext()), capacity_lane("control"):
        _consume(settings, once=args.once)


def _consume(settings: ZebraAgentSettings, *, once: bool) -> None:
    database = PostgresDatabase(
        settings.database_url, deployment_namespace=os.environ.get("ZEBRA_DEPLOYMENT_NAMESPACE", "")
    )
    owner, engine = f"cleanup:{uuid4()}", None
    while True:
        try:
            try:
                engine = engine or pin_cloud_engine(settings)
            except Exception:
                logging.warning("runtime_cleanup_engine_unavailable")
            forced = recover_force_stops(
                database._dsn, deployment_namespace=database.deployment_namespace, engine=engine
            )
            if engine is None:
                if once:
                    return
                time.sleep(2)
                continue
            settled = cleanup_runtime_batch(
                database._dsn,
                deployment_namespace=database.deployment_namespace,
                owner=owner,
                engine=engine,
                batch_size=1,
            )
            if settled or forced:
                logging.warning("runtime_cleanup_settled count=%s", settled + forced)
        except Exception as error:
            logging.warning("runtime_cleanup_deferred error_type=%s", type(error).__name__)
            if once:
                raise
        if once:
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
