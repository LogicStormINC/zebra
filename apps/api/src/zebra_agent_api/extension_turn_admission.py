"""Server-owned Skill snapshot selection for cloud message admission."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from agent_core.application import current_turn, project_turns
from agent_core.application.turn_projection import TurnRecord
from agent_core.contracts import (
    SessionCommandAcceptedPayload,
    SessionCommandKind,
    is_command_message_materialization,
    validate_accepted_session_command,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope, SkillInstallation
from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import TurnStatus, derive_turn_id
from agent_core.ports.extension_snapshots import ExtensionSnapshotStore, ExtensionTaskAuthorityStore
from agent_core.ports.extensions import (
    ExtensionPageRequest,
    ExtensionSkillConflictError,
    ExtensionStore,
)
from agent_core.ports.mcp_catalog import McpCatalogStore
from agent_security.extension_authority import extension_runtime_scope_from_task_grant
from agent_security.host_grant import VerifiedHostGrant

from zebra_agent_api.extension_mcp_selection import select_enabled_mcp

_MAX_SNAPSHOT_SKILLS = 32
_MAX_SCANNED_SKILLS = 400
_MAX_SCANNED_PAGES = 4
_RESERVED_CLIENT_FIELDS = frozenset(
    {
        "extension_snapshot_digest",
        "extension_turn_id",
        "extension_snapshot",
        "snapshot_ref",
    }
)


class ClientExtensionBindingError(ValueError):
    """A client attempted to supply a server-owned snapshot binding."""


class PendingMessageCommandError(ValueError):
    """The prior message must materialize before another Turn can be admitted."""


class CloudExtensionTurnAdmission:
    """Select bounded live configuration; the result is not execution authority."""

    def __init__(
        self,
        store: ExtensionStore,
        snapshots: ExtensionSnapshotStore,
        task_authority: ExtensionTaskAuthorityStore,
        *,
        mcp_catalogs: McpCatalogStore | None = None,
    ) -> None:
        self._store = store
        self._snapshots = snapshots
        self._task_authority = task_authority
        self._mcp_catalogs = mcp_catalogs

    def authorize(
        self,
        *,
        verified: VerifiedHostGrant,
        session_id: SessionId,
    ) -> tuple[ExtensionScope, ExtensionTaskCeiling]:
        """Validate live authority against the frozen root Task before disclosure."""

        ceiling = self._task_authority.resolve_task_ceiling(session_id=str(session_id))
        scope = extension_runtime_scope_from_task_grant(verified, ceiling.binding)
        return scope, ceiling

    def prepare(
        self,
        *,
        verified: VerifiedHostGrant,
        session_id: SessionId,
        events: list[SessionEvent],
        client_payload: dict[str, object],
        authorized: tuple[ExtensionScope, ExtensionTaskCeiling] | None = None,
        existing_turn: bool = False,
    ) -> tuple[ExtensionScope, ExtensionSnapshot, ExtensionTaskCeiling]:
        forbidden = sorted(_RESERVED_CLIENT_FIELDS & client_payload.keys())
        if forbidden:
            raise ClientExtensionBindingError(
                f"reserved extension fields are server-owned: {', '.join(forbidden)}"
            )
        if self._has_pending_message(events):
            raise PendingMessageCommandError("the previous message command is still pending")
        scope, ceiling = authorized or self.authorize(
            verified=verified,
            session_id=session_id,
        )
        clarification_id = client_payload.get("clarification_id")
        open_turn = None
        if existing_turn:
            open_turn = current_turn(events)
            if open_turn is None or open_turn.legacy:
                raise ClientExtensionBindingError("execution requires an active non-legacy Turn")
        if isinstance(clarification_id, str) and clarification_id.strip():
            open_turn = self._clarification_turn(events, clarification_id.strip())
        turn_id = (
            open_turn.turn_id
            if open_turn is not None
            else str(derive_turn_id(session_id, len(project_turns(events))))
        )
        prior = self._prior_binding(events, turn_id)
        if prior is not None:
            snapshot = asyncio.run(
                self._snapshots.get(
                    scope=scope,
                    session_id=str(session_id),
                    turn_id=turn_id,
                    expected_digest=prior,
                )
            )
        else:
            snapshot = ExtensionSnapshot(
                scope=scope,
                session_id=str(session_id),
                turn_id=turn_id,
                skills=tuple(self._enabled_skills(scope, ceiling.skill_components)),
                mcp=(
                    asyncio.run(select_enabled_mcp(self._store, self._mcp_catalogs, scope))
                    if self._mcp_catalogs is not None
                    else ()
                ),
            )
        if any(skill.version.skill_id not in ceiling.skill_components for skill in snapshot.skills):
            raise ValueError("extension snapshot exceeds the Task Skill ceiling")
        return scope, snapshot, ceiling

    def _enabled_skills(
        self, scope: ExtensionScope, skill_components: tuple[str, ...]
    ) -> list[SkillInstallation]:
        if not skill_components:
            return []
        return asyncio.run(self._list_enabled_skills(scope, frozenset(skill_components)))

    async def _list_enabled_skills(
        self, scope: ExtensionScope, allowed: frozenset[str]
    ) -> list[SkillInstallation]:
        selected: list[SkillInstallation] = []
        cursor: str | None = None
        scanned = 0
        pages = 0
        while True:
            page = await self._store.list_skills(
                scope=scope,
                page=ExtensionPageRequest(limit=100, cursor=cursor),
            )
            pages += 1
            scanned += len(page.items)
            if scanned > _MAX_SCANNED_SKILLS:
                raise ValueError("extension selection exceeded its bounded scan")
            eligible = tuple(
                item for item in page.items if item.enabled and item.version.skill_id in allowed
            )
            skill_ids = tuple(item.version.skill_id for item in (*selected, *eligible))
            if len(skill_ids) != len(set(skill_ids)):
                raise ExtensionSkillConflictError(
                    "multiple enabled installations exist for one Skill"
                )
            selected.extend(eligible)
            if len(selected) > _MAX_SNAPSHOT_SKILLS:
                raise ValueError("too many enabled Skills for one Turn snapshot")
            if page.next_cursor is None:
                break
            if scanned >= _MAX_SCANNED_SKILLS or pages >= _MAX_SCANNED_PAGES:
                raise ValueError("extension selection exceeded its bounded scan")
            if page.next_cursor == cursor:
                raise ValueError("extension pagination did not advance")
            cursor = page.next_cursor
        return selected

    @staticmethod
    def _prior_binding(events: list[SessionEvent], turn_id: str) -> str | None:
        for event in reversed(events):
            if event.event_type is not EventType.SESSION_COMMAND_ACCEPTED:
                continue
            accepted = SessionCommandAcceptedPayload.model_validate(event.payload)
            if (
                accepted.kind
                in {SessionCommandKind.MESSAGE, SessionCommandKind.RUN, SessionCommandKind.RESUME}
                and accepted.extension_turn_id == turn_id
            ):
                if accepted.extension_snapshot_digest is None:
                    raise ValueError("prior extension Turn binding is incomplete")
                return accepted.extension_snapshot_digest
        return None

    @staticmethod
    def _has_pending_message(events: list[SessionEvent]) -> bool:
        message_types = {EventType.USER_MESSAGE_RECEIVED, EventType.CLARIFICATION_RESPONDED}
        canonical: dict[object, list[SessionEvent]] = defaultdict(list)
        legacy: dict[str, list[SessionEvent]] = defaultdict(list)
        event_ids: dict[object, int] = defaultdict(int)
        accepted_events: list[SessionEvent] = []
        for event in events:
            event_ids[event.event_id] += 1
            if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
                accepted_events.append(event)
                continue
            if event.event_type not in message_types or event.actor is not EventActor.USER:
                continue
            if event.causation_id is not None:
                canonical[event.causation_id].append(event)
            elif event.idempotency_key is not None:
                legacy[event.idempotency_key].append(event)
        for event in accepted_events:
            if event_ids[event.event_id] != 1:
                raise ValueError("accepted message materialization integrity check failed")
            accepted = validate_accepted_session_command(
                event.payload,
                session_id=event.session_id,
                idempotency_key=event.idempotency_key,
            )
            if accepted.kind is not SessionCommandKind.MESSAGE:
                continue
            legacy_key = f"{accepted.idempotency_key}:message"
            candidates = {
                candidate.event_id: candidate
                for candidate in (
                    *canonical.get(event.event_id, ()),
                    *legacy.get(legacy_key, ()),
                )
                if candidate.session_id == event.session_id
                and is_command_message_materialization(
                    causation_id=candidate.causation_id,
                    idempotency_key=candidate.idempotency_key,
                    accepted_event_id=event.event_id,
                    accepted_idempotency_key=accepted.idempotency_key,
                )
            }
            if not candidates:
                return True
            if len(candidates) != 1:
                raise ValueError("accepted message materialization integrity check failed")
        return False

    @staticmethod
    def _clarification_turn(events: list[SessionEvent], clarification_id: str) -> TurnRecord:
        open_turn = current_turn(events)
        if open_turn is None or open_turn.status is not TurnStatus.WAITING_INPUT:
            raise ClientExtensionBindingError("there is no active clarification")
        requested = next(
            (
                event
                for event in reversed(events)
                if event.event_type is EventType.CLARIFICATION_REQUESTED
            ),
            None,
        )
        if requested is None or requested.payload.get("clarification_id") != clarification_id:
            raise ClientExtensionBindingError("clarification_id does not match the active request")
        return open_turn
