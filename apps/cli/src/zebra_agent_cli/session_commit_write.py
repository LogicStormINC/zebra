from __future__ import annotations

from pathlib import Path

from zebra_agent_api.session_commit import SessionCommitApi


def commit_session(
    *,
    database_path: Path,
    session_id: str,
    message: str,
    author_name: str,
    author_email: str,
    idempotency_key: str | None,
) -> dict[str, object]:
    response = SessionCommitApi(database_path).commit(
        session_id,
        {
            "message": message,
            "author_name": author_name,
            "author_email": author_email,
        },
        idempotency_key=idempotency_key,
    )
    return {
        **response.body,
        "database": str(database_path),
    }
