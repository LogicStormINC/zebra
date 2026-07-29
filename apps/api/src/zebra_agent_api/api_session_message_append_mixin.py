from __future__ import annotations

from pathlib import Path

from agent_core.application import (
    SessionMessageAppendCommand,
    SessionMessageAppendService,
    attach_refs_to_user_event,
)
from agent_core.application.session_projection import apply_event
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    store_text_attachments,
)
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse, bad_request, conflict
from zebra_agent_api.session_payloads import parse_append_session_message_payload
from zebra_agent_api.task_image_attachments import (
    cleanup_staged_task_images,
    stage_task_images,
)


class ApiSessionMessageAppendMixin:
    database_path: Path
    settings: ZebraAgentSettings

    def append_session_message(
        self,
        session_id: str,
        payload: dict[str, object],
        *,
        task_id: str | None = None,
    ) -> ApiResponse:
        parsed = parse_append_session_message_payload(payload)
        if isinstance(parsed, ApiResponse):
            return parsed
        session_key = self._parse_session_id(session_id)
        if isinstance(session_key, ApiResponse):
            return session_key
        projection_store = SQLiteProjectionStore(self.database_path)
        session = projection_store.get_session(session_key)
        if session is None:
            return ApiResponse(404, {"session_id": session_id, "status": "not_found"})
        staged_images = None
        images_durable = False
        try:
            if parsed["image_attachments"]:
                staged_images = stage_task_images(
                    self.settings,
                    task_id=task_id or str(session_key),
                    images=parsed["image_attachments"],
                )
        except ValueError as exc:
            return bad_request(str(exc))
        try:
            event = SessionMessageAppendService().build_event(
                session=session,
                next_sequence=session.current_sequence + 1,
                command=SessionMessageAppendCommand(
                    content=parsed["content"],
                    clarification_id=parsed["clarification_id"],
                    public_content=parsed["public_content"],
                ),
            )
        except ValueError as exc:
            if staged_images is not None:
                cleanup_staged_task_images(staged_images)
            return conflict(
                session_id=session_id,
                status="not_appendable",
                reason=(
                    "cannot_append_to_terminal_session"
                    if "terminal session" in str(exc)
                    else str(exc)
                ),
            )
        try:
            attachment_store = SQLiteArtifactPayloadStore(self.database_path)
            attachment_refs = store_text_attachments(
                attachment_store,
                session_id=session_key,
                message_event=event,
                attachments=parsed["attachments"],
                created_at=event.created_at,
            )
            event = attach_refs_to_user_event(event, attachment_refs)
            if staged_images is not None:
                staged_images.persist_payloads(
                    attachment_store,
                    session_id=session_key,
                    created_at=event.created_at,
                )
                image_refs = staged_images.refs_for(event.event_id)
                event = attach_refs_to_user_event(event, image_refs)
                attachment_refs = (*attachment_refs, *image_refs)
            SQLiteEventStore(self.database_path).append(event)
            images_durable = True
            updated_session = projection_store.save_session(apply_event(session, event))
        except Exception:
            if staged_images is not None and not images_durable:
                cleanup_staged_task_images(staged_images)
            raise
        body: dict[str, object] = {
            "session_id": session_id,
            "appended": True,
            **(
                {
                    "clarification_resolved": True,
                    "clarification_id": parsed["clarification_id"],
                }
                if event.event_type.value == "clarification_responded"
                else {}
            ),
            "content": parsed["content"],
            "sequence": event.sequence,
            "status": updated_session.status.value,
            "current_sequence": updated_session.current_sequence,
        }
        if attachment_refs:
            body["attachments"] = [ref.to_mapping() for ref in attachment_refs]
        return ApiResponse(201, body)

    def _parse_session_id(self, session_id: str) -> SessionId | ApiResponse:
        raise NotImplementedError
