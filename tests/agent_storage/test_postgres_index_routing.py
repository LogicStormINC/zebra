"""Each committed event reaches only the index that can consume it."""

from unittest.mock import Mock

import pytest
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.model_tool_projection import ModelToolProjectionPort
from agent_storage.postgres_model_tool_compat import (
    PostgresModelCallProjectionAdapter,
    PostgresToolRunProjectionAdapter,
)


@pytest.mark.parametrize("kind", list(EventType))
def test_event_routes_to_at_most_one_fenced_projection(kind: EventType) -> None:
    projection = Mock(spec=ModelToolProjectionPort)
    projection.index_worker_event.return_value = None
    event = SessionEvent.model_construct(event_type=kind)
    authority = Mock(spec=WorkerMutationAuthority)

    PostgresModelCallProjectionAdapter(projection).index_worker_event(event, authority=authority)
    PostgresToolRunProjectionAdapter(projection).index_worker_event(event, authority=authority)

    if kind in {
        EventType.MODEL_RESPONSE_RECEIVED,
        EventType.TOOL_EXECUTION_COMPLETED,
        EventType.TOOL_EXECUTION_FAILED,
    }:
        projection.index_worker_event.assert_called_once_with(event, authority=authority)
    else:
        projection.index_worker_event.assert_not_called()
