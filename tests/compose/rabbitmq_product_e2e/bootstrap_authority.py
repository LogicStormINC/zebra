"""Post-migration host authority bootstrap, only inside the dedicated fixture."""

import importlib
import os
from pathlib import Path

from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore


def main() -> None:
    namespace = os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"]
    if namespace != "rabbitmq-product-e2e":
        raise ValueError("refusing non-fixture namespace")
    dsn = os.environ["ZEBRA_DATABASE_URL"]
    from psycopg.conninfo import conninfo_to_dict

    target = conninfo_to_dict(dsn)
    if (
        target.keys() - {"host", "port", "dbname", "user", "password"}
        or target.get("host") != "postgres"
        or target.get("dbname") not in {"zebra_e2e", "zebra_stage3_e2e"}
        or target.get("port") != "5432"
        or target.get("user") != "e2e"
    ):
        raise ValueError("refusing non-fixture database")
    for name in ("agent_core", "agent_storage", "zebra_agent_api", "zebra_agent_worker"):
        origin = Path(importlib.import_module(name).__file__).resolve()
        if not origin.is_relative_to("/app/packages") and not origin.is_relative_to("/app/apps"):
            raise ValueError("application imports do not resolve to mounted isolated source")
    issuer = "https://broker.zebra.local:28443"
    store = PostgresHostAuthorityStore(dsn, deployment_namespace=namespace)
    store.upsert_registry(
        HostRegistryRecord(
            host_app_id="trench",
            namespace_id="trench-rabbitmq-e2e",
            issuer=issuer,
            audience="zebra",
            jwks_uri=f"{issuer}/.well-known/jwks.json",
            allowed_origins=("https://127.0.0.1:28443",),
            algorithms=("RS256",),
            policy_version="trench-native-v2",
        )
    )
    print("isolated source imports and Host authority registered")


if __name__ == "__main__":
    main()
