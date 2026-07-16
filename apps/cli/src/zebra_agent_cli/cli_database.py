from __future__ import annotations

from pathlib import Path

from zebra_agent_config import ZebraAgentSettings


def _database_path(
    database: str | None,
    settings: ZebraAgentSettings,
) -> Path:
    return Path(database or settings.database_url)
