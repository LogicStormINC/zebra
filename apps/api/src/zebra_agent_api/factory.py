from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from agent_integrations import GitHubPullRequestTransport
from agent_security import CredentialBroker
from agent_storage import (
    CloudCompositionSettings,
    ControlPlaneStores,
    compose_control_plane_stores,
)
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_api.credential_broker import build_default_credential_broker
from zebra_agent_api.session_context_namespace import resolve_context_namespace

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi


def create_app(
    database_path: str | Path | None = None,
    *,
    settings: ZebraAgentSettings | None = None,
    stores: ControlPlaneStores | None = None,
    cloud_composition: CloudCompositionSettings | None = None,
    administrative_context_namespace: str | None = None,
    context_administrative_namespace: str | None = None,
    credential_broker: CredentialBroker | None = None,
    credential_env: Mapping[str, str] | None = None,
    github_transport: GitHubPullRequestTransport | None = None,
) -> ZebraAgentApi:
    from zebra_agent_api.app import ZebraAgentApi

    active_settings = settings or load_settings()
    active_database_path = Path(database_path or active_settings.database_url)
    active_stores = stores
    if active_stores is None and active_settings.profile == "cloud":
        active_stores = compose_control_plane_stores(
            profile="cloud",
            database_path=active_settings.database_url,
            cloud=cloud_composition,
        )
    active_broker = credential_broker
    if active_broker is None:
        active_broker = build_default_credential_broker(active_settings.scm, env=credential_env)
    return ZebraAgentApi(
        database_path=active_database_path,
        settings=active_settings,
        _stores=active_stores,
        administrative_context_namespace=resolve_context_namespace(
            administrative_context_namespace, context_administrative_namespace
        ),
        credential_broker=active_broker,
        github_transport=github_transport,
    )
