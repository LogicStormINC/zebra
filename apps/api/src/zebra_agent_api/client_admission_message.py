"""Opt-in original-message condition; legacy admission models and hashes stay unchanged."""

from typing import Any, Literal

from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.projections import PostgresProjectionStore
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from zebra_agent_api.client_admission_operations import Admission

PROTOCOL = "atomic-message-surface/1"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class OriginalMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    receipt_key: str = Field(min_length=1, max_length=128, pattern=r"^[!-~]+$")
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str = Field(pattern=UUID_PATTERN)
    segment_id: str = Field(pattern=UUID_PATTERN)
    segment_sequence: StrictInt = Field(ge=0, le=9007199254740991)


class MessageSurfaceAdmission(Admission):
    kind: Literal["surface_mount"]
    task: str = Field(pattern=UUID_PATTERN)
    original_message: OriginalMessage


def validate_message_surface(app: Any, raw: dict[str, Any]) -> MessageSurfaceAdmission:
    from zebra_agent_api.client_admission_atomic import eligible_atomic_surface
    from zebra_agent_api.client_surface import ClientSurfaceRequest

    body = MessageSurfaceAdmission.model_validate(raw)
    if getattr(app, "client_platform", None) is None or not eligible_atomic_surface(app):
        raise ValueError("message surface requires exact same PG ports")
    database = app.stores.idempotency._database
    for port, expected in (
        (app.stores.tasks, PostgresAgentTaskStore),
        (app.stores.events, PostgresEventStore),
        (app.stores.sessions, PostgresProjectionStore),
    ):
        if type(port) is not expected or (
            port._database._dsn,
            port._database.deployment_namespace,
        ) != (database._dsn, database.deployment_namespace):
            raise ValueError("message source requires exact same PG ports")
    ClientSurfaceRequest.model_validate(body.payload)
    return body
