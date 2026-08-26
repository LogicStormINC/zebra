"""Register a Host issuer binding in the Zebra PostgreSQL host authority store.

Usage:
    uv run python scripts/register_trench_host.py \
        --dsn "$ZEBRA_E2E_DATABASE_DSN" \
        --deployment-namespace zebra \
        --host-app-id trench \
        --namespace-id trench-prod \
        --issuer https://broker.zebra.local \
        --audience zebra \
        --jwks-uri https://broker.zebra.local/.well-known/jwks.json \
        --origin https://trench.zebra.local \
        --policy-version trench-read-v1

The upsert is idempotent on (deployment_namespace, host_app_id, namespace_id).
"""

from __future__ import annotations

import argparse
import sys

from agent_storage.postgres.host_auth import (
    HostRegistryRecord,
    PostgresHostAuthorityStore,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="Zebra PostgreSQL DSN")
    parser.add_argument("--deployment-namespace", required=True)
    parser.add_argument("--host-app-id", required=True)
    parser.add_argument("--namespace-id", required=True)
    parser.add_argument("--issuer", required=True, help="HTTPS origin of the grant broker")
    parser.add_argument("--audience", required=True)
    parser.add_argument("--jwks-uri", required=True, help="HTTPS JWKS URL of the broker")
    parser.add_argument(
        "--origin",
        dest="origins",
        action="append",
        required=True,
        help="Allowed HTTPS origin of the Host BFF (repeatable)",
    )
    parser.add_argument("--policy-version", required=True)
    parser.add_argument(
        "--deactivate",
        action="store_true",
        help="Upsert the binding as inactive instead of active",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    store = PostgresHostAuthorityStore(
        args.dsn, deployment_namespace=args.deployment_namespace
    )
    record = HostRegistryRecord(
        host_app_id=args.host_app_id,
        namespace_id=args.namespace_id,
        issuer=args.issuer,
        audience=args.audience,
        jwks_uri=args.jwks_uri,
        allowed_origins=tuple(args.origins),
        algorithms=("RS256",),
        policy_version=args.policy_version,
        active=not args.deactivate,
    )
    stored = store.upsert_registry(record)
    print(
        "registered: "
        f"deployment={store.deployment_namespace} "
        f"host_app={stored.host_app_id} namespace={stored.namespace_id} "
        f"issuer={stored.issuer} audience={stored.audience} "
        f"jwks={stored.jwks_uri} origins={','.join(stored.allowed_origins)} "
        f"active={stored.active}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
