"""Trench session validation: forward the Host cookie to Trench's viewer endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class TrenchSessionError(RuntimeError):
    """Raised when the forwarded session cannot be validated by the Host."""


@dataclass(frozen=True, slots=True)
class TrenchViewer:
    user_id: str
    workspace_id: str
    active_source_ids: frozenset[str] = frozenset()


def fetch_viewer(
    me_url: str,
    sources_url: str,
    cookie: str,
    *,
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> TrenchViewer:
    """Validate the session synchronously; only the Cookie header crosses the boundary."""

    headers = {"Accept": "application/json", "Cookie": cookie}
    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            response = client.get(me_url, headers=headers)
            sources_response = client.get(sources_url, headers=headers)
    except httpx.HTTPError as exc:
        raise TrenchSessionError("trench_unreachable") from exc
    if response.status_code in {401, 403}:
        raise TrenchSessionError("session_inactive")
    if response.status_code != 200:
        raise TrenchSessionError("trench_unexpected_status")
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise TrenchSessionError("trench_response_invalid") from exc
    viewer = payload.get("data", {}).get("viewer") if isinstance(payload, dict) else None
    if not isinstance(viewer, dict):
        raise TrenchSessionError("viewer_missing")
    user_id = viewer.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 512:
        raise TrenchSessionError("viewer_identity_invalid")
    workspace = viewer.get("workspace_id")
    workspace_id = (
        workspace.strip()
        if isinstance(workspace, str) and workspace.strip() and len(workspace) <= 512
        else ""
    )
    if sources_response.status_code in {401, 403}:
        raise TrenchSessionError("session_inactive")
    if sources_response.status_code != 200:
        raise TrenchSessionError("trench_unexpected_status")
    try:
        sources_payload: Any = sources_response.json()
    except ValueError as exc:
        raise TrenchSessionError("trench_response_invalid") from exc
    items = (
        sources_payload.get("data", {}).get("items")
        if isinstance(sources_payload, dict)
        else None
    )
    if not isinstance(items, list):
        raise TrenchSessionError("sources_missing")
    source_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise TrenchSessionError("sources_invalid")
        source_id = item.get("source_id")
        status = item.get("subscription_status", item.get("status"))
        if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 512:
            raise TrenchSessionError("sources_invalid")
        if status in {None, "active"}:
            source_ids.add(source_id.strip())
    return TrenchViewer(
        user_id=user_id.strip(),
        workspace_id=workspace_id,
        active_source_ids=frozenset(source_ids),
    )
