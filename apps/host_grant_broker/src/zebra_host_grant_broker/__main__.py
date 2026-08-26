"""Uvicorn entry point: `python -m zebra_host_grant_broker`."""

from __future__ import annotations

import uvicorn

from zebra_host_grant_broker.config import BrokerSettings


def main() -> None:
    BrokerSettings.from_env()  # fail fast on invalid configuration
    uvicorn.run(
        "zebra_host_grant_broker.runtime:app",
        host="0.0.0.0",
        port=8090,
        log_level="info",
        factory=False,
    )


if __name__ == "__main__":
    main()
