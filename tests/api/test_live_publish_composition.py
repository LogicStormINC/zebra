from __future__ import annotations

from pathlib import Path

from agent_integrations import RedisCommittedEventPublisher
from agent_storage import PostCommitPublishingEventStore, sqlite_control_plane_stores
from zebra_agent_api.app import create_app
from zebra_agent_config import load_settings


def test_api_composition_wraps_event_store_when_live_publisher_is_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    publisher = object()
    monkeypatch.setattr(
        RedisCommittedEventPublisher,
        "from_url",
        classmethod(lambda cls, *args, **kwargs: publisher),
    )
    database_path = tmp_path / "live.sqlite"
    settings = load_settings(
        {
            "ZEBRA_PROFILE": "local",
            "ZEBRA_DATABASE_URL": str(database_path),
            "ZEBRA_LIVE_REDIS_URL": "redis://redis-live:6379/0",
        }
    )

    app = create_app(
        database_path,
        settings=settings,
        stores=sqlite_control_plane_stores(database_path),
    )

    assert isinstance(app.stores.events, PostCommitPublishingEventStore)
