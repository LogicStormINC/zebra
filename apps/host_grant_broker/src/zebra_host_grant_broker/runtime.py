"""Module-level app built from process environment for uvicorn."""

from __future__ import annotations

from zebra_host_grant_broker.app import create_app
from zebra_host_grant_broker.config import BrokerSettings

app = create_app(BrokerSettings.from_env())
