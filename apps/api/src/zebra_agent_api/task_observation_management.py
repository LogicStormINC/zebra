"""Read-only Task observation for the management plane, scoped to one namespace.

管理面（overdoze）经交付信任代理读任务坐标：只暴露坐标/状态/进度，标题等用户内容、
事件正文与凭据线索永不出域（跨仓合同 task-observations/v1 的硬边界）。
"""

from __future__ import annotations

from functools import partial

import psycopg
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.host_registry_config import load_host_management_config
from zebra_agent_api.management_transport import authorize_management, register_management_endpoint
from zebra_agent_api.runtime_management import _error

CONTRACT = "task-observation-management/1"
PATH = "/management/v1/task-observations"
REQUEST_TIMEOUT = 5.0
OBSERVATION_LIMIT = 25


def _perform(
    settings: ZebraAgentSettings,
    namespace: str | None,
    token: str,
    headers: dict[str, list[str]],
    method: str,
    body: dict[str, object] | None,
) -> JSONResponse:
    config = load_host_management_config(settings.host_management_config, namespace)
    denied = authorize_management(config, token, headers, "tasks.read")
    if denied is not None:
        return denied
    if method != "GET" or body is not None:
        return _error(405, "METHOD_NOT_ALLOWED")
    if namespace is None or not settings.database_url.startswith(("postgres://", "postgresql://")):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    store = PostgresAgentTaskStore(settings.database_url, deployment_namespace=namespace)
    try:
        tasks = store.list_tasks(limit=OBSERVATION_LIMIT)
    except (OSError, psycopg.Error):
        return _error(503, "MANAGEMENT_UNAVAILABLE")
    return JSONResponse(
        content={
            "contractVersion": CONTRACT,
            "namespace": namespace,
            "tasks": [
                {
                    "taskId": str(task.task_id),
                    "status": task.status.value,
                    "activeSegmentId": str(task.active_segment_id),
                    "currentSequence": task.current_sequence,
                }
                for task in tasks
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


def register_task_observation_management(
    app: FastAPI, settings: ZebraAgentSettings, namespace: str | None
) -> None:
    register_management_endpoint(
        app, PATH, partial(_perform, settings, namespace), timeout=REQUEST_TIMEOUT
    )
