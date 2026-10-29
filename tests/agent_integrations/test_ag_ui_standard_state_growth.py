"""Ten thousand stable identities grow indexed membership, not checkpoint payloads."""

import json
from uuid import uuid4

from agent_core.domain.events import EventType
from agent_core.ports.task_projection_checkpoints import ProjectionCell
from agent_integrations.ag_ui.standard_checkpoint import (
    load_membership,
    load_standard,
    save_membership,
    save_standard,
)
from agent_integrations.ag_ui.standard_usage import record_usage

from tests.agent_integrations.test_ag_ui_standard_projection import source


def test_ten_thousand_call_ids_keep_point_reads_and_checkpoint_payload_bounded():
    root = uuid4()
    cells = {}
    position = 0
    maximum_keys = 0

    def load(keys):
        nonlocal maximum_keys
        maximum_keys = max(maximum_keys, len(keys))
        selected = tuple(cells[k] for k in keys if k in cells)
        assert all(c.task_sequence < position for c in selected)
        return selected

    def change(key, at, value):
        cells[key] = ProjectionCell(key, at, value)

    # A whole-history snapshot has a real ceiling even with no model bodies.
    assert len(json.dumps({"seen_usage": [f"call-{i:05}" for i in range(10_000)]})) > 32_768
    for position in range(10_000):
        event = source(
            position,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"model_call_id": f"call-{position:05}", "input_tokens": 1},
            root,
        )
        state = load_standard(root, load)
        state.protocol_run_id = "agui:" + "1" * 64
        state.continuation_id = str(root)
        state.started = True
        load_membership(root, event, state, load)
        record_usage(event.payload, state, 0)
        save_standard(root, state, change, position)
        save_membership(root, event, state, change, position)
        assert len(state.snapshot().encode()) < 1024
        assert len(state.seen_usage) == 1
    assert state.usage == [{"inputTokens": 10_000}]
    assert maximum_keys <= 1
    assert len(cells) == 10_002  # count + one small active snapshot + indexed call IDs.
