import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.session_history import SessionHistoryMode, SessionHistoryRequest
from agent_core.domain.tool_runs import ToolRunRecord
from agent_storage import sqlite_control_plane_stores

_TARGET_CONSTRUCTORS = re.compile(
    r"\bSQLite(?:AgentTaskStore|ArtifactPayloadStore|ArtifactStore|"
    r"ContextLifecycleStore|"
    r"DeliveryAuditStore|EffectLedger|HandoffDispatchStore|IdempotencyStore|"
    r"LeaseStore|MemoryStore|ModelCallStore|ProjectionStore|"
    r"ProviderContinuationStore|SessionHandoffStore|SessionHistory|ToolRunStore|"
    r"WorkspaceProjectionStore|EventStore)\("
)


def test_api_and_worker_have_no_authoritative_sqlite_constructor_bypasses() -> None:
    repository = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for relative_root in (
        "apps/api/src/zebra_agent_api",
        "apps/worker/src/zebra_agent_worker",
    ):
        for source in sorted((repository / relative_root).rglob("*.py")):
            for line_number, line in enumerate(source.read_text().splitlines(), start=1):
                if _TARGET_CONSTRUCTORS.search(line):
                    violations.append(
                        f"{source.relative_to(repository)}:{line_number}: {line.strip()}"
                    )

    assert violations == []


def test_indexes_continuations_and_history_stay_on_authoritative_backend(
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "authority.sqlite"
    legacy_path = tmp_path / "legacy.sqlite"
    stores = sqlite_control_plane_stores(authority_path)
    created_at = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Prior authoritative task",
            user_input="Keep the continuation and artifact indexes.",
            workspace_root=tmp_path.resolve(),
            created_at=created_at,
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    stores.sessions.save_session(bootstrap.session)
    session_id = bootstrap.session.session_id
    stores.model_calls.upsert(
        ModelCallRecord(
            session_id=session_id,
            sequence=4,
            provider="test",
            model_name="test-model",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            latency_ms=20,
            cache_hit=False,
            cost_usd=0.0,
            assistant_message="Indexed on backend B.",
            tool_call_count=1,
            created_at=created_at,
        )
    )
    stores.tool_runs.upsert(
        ToolRunRecord(
            session_id=session_id,
            sequence=5,
            tool_name="tests.run",
            status="executed",
            idempotency_key="tool-5",
            output="passed",
            artifact_uri=None,
            created_at=created_at,
        )
    )
    reference = ProviderContinuationRef(
        reference_id="response-b",
        provider="test",
        model_name="test-model",
        capability_version="responses.v1",
        source_hash="b" * 64,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
    )
    continuation = stores.provider_continuations.store(
        tenant_id="tenant-b",
        session_id=str(session_id),
        reference=reference,
        opaque_payload=b"opaque-backend-b",
    )

    assert [artifact.artifact_id for artifact in stores.artifacts.list_for_session(session_id)] == [
        "model-call:4",
        "tool-run:5",
    ]
    loaded = stores.provider_continuations.load_compatible(
        continuation.artifact_id,
        tenant_id="tenant-b",
        provider="test",
        model_name="test-model",
        capability_version="responses.v1",
        as_of=created_at,
    )
    assert loaded is not None
    assert loaded.opaque_payload == b"opaque-backend-b"
    history = stores.session_history.scoped((str(session_id),)).query(
        SessionHistoryRequest(mode=SessionHistoryMode.READ, session_id=str(session_id))
    )
    assert [message.content for message in history.messages] == [
        "Keep the continuation and artifact indexes."
    ]

    assert not legacy_path.exists()
    legacy = sqlite_control_plane_stores(legacy_path)
    assert legacy.artifacts.list_for_session(session_id) == []
    assert (
        legacy.provider_continuations.load_compatible(
            continuation.artifact_id,
            tenant_id="tenant-b",
            provider="test",
            model_name="test-model",
            capability_version="responses.v1",
            as_of=created_at,
        )
        is None
    )
    legacy_history = legacy.session_history.scoped((str(session_id),)).query(
        SessionHistoryRequest(mode=SessionHistoryMode.READ, session_id=str(session_id))
    )
    assert legacy_history.messages == ()
