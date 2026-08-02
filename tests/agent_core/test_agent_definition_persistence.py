from pathlib import Path

import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventType
from agent_storage import SQLiteArtifactPayloadStore, SQLiteWorkspaceProjectionStore
from zebra_agent_worker.task_recovery import recover_task


def test_definition_survives_bootstrap_workspace_round_trip_and_recovery(
    tmp_path: Path,
) -> None:
    definition = _definition()
    bootstrapped = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Persistent definition",
            user_input="Collect typed evidence.",
            workspace_root=tmp_path,
            agent_definition=definition,
        )
    )
    events = list(bootstrapped.events)
    workspace = rebuild_workspace(events)
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    store.save_workspace(workspace)
    loaded = store.get_workspace(bootstrapped.session.session_id)
    assert loaded is not None
    assert loaded.agent_definition == definition
    prepared = next(event for event in events if event.event_type is EventType.TASK_PREPARED)
    assert prepared.payload["agent_definition"]["version"] == "1.0.0"

    recovered = recover_task(
        events,
        workspace=loaded,
        fallback_title="fallback",
        attachment_store=SQLiteArtifactPayloadStore(tmp_path / "artifacts.db"),
    )

    assert recovered.agent_definition == definition


def test_recovery_rejects_definition_projection_drift(tmp_path: Path) -> None:
    bootstrapped = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Tamper check",
            user_input="Collect typed evidence.",
            workspace_root=tmp_path,
            agent_definition=_definition(),
        )
    )
    events = list(bootstrapped.events)
    workspace = rebuild_workspace(events)
    tampered = events[-1].model_copy(
        update={
            "payload": {
                **events[-1].payload,
                "agent_definition": {
                    **events[-1].payload["agent_definition"],
                    "version": "2.0.0",
                },
            }
        }
    )

    with pytest.raises(ValueError, match="agent_definition drift"):
        recover_task(
            [*events[:-1], tampered],
            workspace=workspace,
            fallback_title="fallback",
            attachment_store=SQLiteArtifactPayloadStore(tmp_path / "artifacts.db"),
        )


def _definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
            )
        ),
    )
