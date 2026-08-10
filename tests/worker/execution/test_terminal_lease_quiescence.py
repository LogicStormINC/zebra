from pathlib import Path
from threading import Event, Thread

import zebra_agent_worker.execution_finalization as finalization
from agent_core.domain.sessions import SessionStatus
from agent_storage import SQLiteLeaseStore, SQLiteProjectionStore
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _seed_ready_session,
)
from zebra_agent_api.task_final_identity import final_message_identity


def test_completed_terminal_is_not_visible_before_worker_lease_is_released(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "worker.db"
    session_id = _seed_ready_session(database, tmp_path)
    extraction_started = Event()
    unblock_extraction = Event()
    worker_error: list[BaseException] = []
    original_extract = finalization.MemoryCandidateExtractionService.extract

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    def block_extraction(self, **kwargs):  # type: ignore[no-untyped-def]
        extraction_started.set()
        assert unblock_extraction.wait(timeout=5)
        return original_extract(self, **kwargs)

    monkeypatch.setattr(
        finalization.MemoryCandidateExtractionService,
        "extract",
        block_extraction,
    )

    def execute() -> None:
        try:
            _build_execution_service(database).execute_session(
                session_id,
                worker_id="worker-a",
                executed_at=_created_at(),
            )
        except BaseException as exc:  # pragma: no cover - raised below in test thread
            worker_error.append(exc)

    worker = Thread(target=execute)
    worker.start()
    try:
        assert extraction_started.wait(timeout=5)
        session = SQLiteProjectionStore(database).get_session(session_id)
        assert session is not None
        assert session.status is not SessionStatus.COMPLETED
        assert SQLiteLeaseStore(database).get(session_id) is not None
    finally:
        unblock_extraction.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not worker_error
    session = SQLiteProjectionStore(database).get_session(session_id)
    assert session is not None
    assert session.status is SessionStatus.COMPLETED
    assert SQLiteLeaseStore(database).get(session_id) is None
    assert final_message_identity(database, str(session_id)) is not None
