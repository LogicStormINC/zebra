"""Bootstrap authority and command rollout for a verified synthetic corpus."""

import argparse
import json
import os

import psycopg
from agent_storage import (
    HostRegistryRecord,
    PostgresHostAuthorityStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.command_wakeup_discovery import begin_command_backfill
from native_corpus import verify_corpus


def bootstrap(dsn: str, namespace: str, tasks: int) -> dict[str, str | int]:
    evidence = verify_corpus(dsn, namespace, tasks)
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as connection:
        if connection.execute(
            """SELECT 1 FROM session_events WHERE deployment_namespace=%s
               AND event_type='session_command_accepted' LIMIT 1""",
            (namespace,),
        ).fetchone():
            raise ValueError("corpus already contains command history")
        current_epoch = connection.execute(
            "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s", (namespace,)
        ).fetchone()
    registry = HostRegistryRecord(
        host_app_id="ha-e1",
        namespace_id="ha-e1-20261102",
        issuer="https://127.0.0.1:28444",
        audience="zebra",
        jwks_uri="https://127.0.0.1:28444/.well-known/jwks.json",
        allowed_origins=("https://ha-e1.invalid",),
        algorithms=("RS256",),
        policy_version="host-v1",
    )
    store = PostgresHostAuthorityStore(dsn, deployment_namespace=namespace)
    current = store.get_registry(
        host_app_id=registry.host_app_id, namespace_id=registry.namespace_id
    )
    if current is not None and current != registry:
        raise ValueError("unexpected existing corpus authority")
    epoch = (
        current_epoch[0]
        if current_epoch is not None
        else bootstrap_control_plane_epoch(dsn, deployment_namespace=namespace)
    )
    if current is None:
        store.upsert_registry(registry)
    progress = begin_command_backfill(dsn, deployment_namespace=namespace)
    if progress.state != "complete":
        raise RuntimeError("unexpected corpus command backfill boundary")
    if verify_corpus(dsn, namespace, tasks) != evidence:
        raise RuntimeError("corpus changed while establishing its runtime authority")
    return {**evidence, "epoch": str(epoch), "command_backfill": progress.state}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("--tasks", type=int, default=10_000)
    args = parser.parse_args()
    print(json.dumps(bootstrap(os.environ["ZEBRA_E1_CORPUS_DSN"], args.namespace, args.tasks)))


if __name__ == "__main__":
    main()
