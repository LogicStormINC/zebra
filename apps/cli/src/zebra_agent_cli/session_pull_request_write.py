from __future__ import annotations

from pathlib import Path

from zebra_agent_api.app import create_app
from zebra_agent_config import ZebraAgentSettings


def open_session_pull_request(
    *,
    database_path: Path,
    session_id: str,
    title: str,
    body: str,
    base_branch: str,
    head_branch: str | None,
    dry_run: bool,
    idempotency_key: str | None,
    settings: ZebraAgentSettings,
) -> dict[str, object]:
    response = create_app(
        database_path,
        settings=settings,
    ).open_session_pull_request(
        session_id,
        {
            "title": title,
            "body": body,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "dry_run": dry_run,
        },
        idempotency_key=idempotency_key,
    )
    return {
        **response.body,
        "database": str(database_path),
    }
