"""API process composition; retain the existing Uvicorn command-line interface."""

import sys
from collections.abc import Sequence
from contextlib import nullcontext

from agent_storage.postgres.connection_pool import postgres_pool_scope
from uvicorn.main import main as uvicorn_main
from zebra_agent_config import load_settings


def main(argv: Sequence[str] | None = None) -> None:
    settings = load_settings()
    # ponytail: reuse the Worker's bounded pool; factory-only/local callers stay unchanged.
    with (
        postgres_pool_scope(settings.database_url)
        if settings.storage_authority == "postgresql"
        else nullcontext()
    ):
        uvicorn_main(
            args=[
                "zebra_agent_api.http:create_http_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                *(sys.argv[1:] if argv is None else argv),
            ]
        )


if __name__ == "__main__":
    main()
