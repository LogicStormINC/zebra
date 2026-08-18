from __future__ import annotations

import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import agent_storage.postgres.session_handoff_authority as authority_module
import psycopg
import pytest
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS
from agent_core.ports.session_handoff import SessionHandoffAbortRequest
from agent_storage import (
    HandoffStorageConflictError,
    apply_postgres_migrations,
    bootstrap_control_plane_epoch,
)

from tests.agent_storage.test_postgres_session_handoffs import (
    NOW,
    _aggregate_counts,
    _create_request,
    _delete_namespace,
    _operation_status,
    _prepared_commit,
    _request_hash,
    _reserve,
    _seed_completed_source,
    _store,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def handoff_namespace(postgres_dsn: str) -> Generator[str, None, None]:
    namespace = f"handoff-authority-{uuid4()}"
    bootstrap_control_plane_epoch(postgres_dsn, deployment_namespace=namespace)
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_concurrent_reserve_retries_converge_to_one_operation(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    request = _create_request(source_id, idempotency_key="concurrent-reserve")
    facts = store.inspect_source_facts(source_id, at=NOW)

    def reserve(_: int) -> object:
        try:
            return _reserve(store, request, facts=facts, request_hash=_request_hash(request))
        except Exception as error:  # pragma: no cover - assertion below reports the failure
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(reserve, (1, 2)))

    assert all(not isinstance(result, Exception) for result in results)
    assert results[0] == results[1]
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*) FROM handoff_operations
            WHERE deployment_namespace = %s
            """,
            (handoff_namespace,),
        ).fetchone()
        assert row is not None and row[0] == 1


def test_abort_rejects_workspace_drift_without_mutating_operation(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, _ = _prepared_commit(store, source_id)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections
            SET workspace_root = %s
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (str(tmp_path / "drifted"), handoff_namespace, source_id),
        )
    authority = AdministrativeMutationCAS(
        deployment_namespace=handoff_namespace,
        session_id=source_id,
        expected_stream_revision=operation.expected_source_stream_version,
    )
    before = _operation_status(postgres_dsn, handoff_namespace, operation.operation_id)

    with pytest.raises(HandoffStorageConflictError, match="authority facts"):
        store.abort_authorized(
            SessionHandoffAbortRequest(
                operation=operation,
                authority=authority,
                code="workspace_drift",
            )
        )

    assert _operation_status(postgres_dsn, handoff_namespace, operation.operation_id) == before


def test_abort_and_commit_race_has_one_terminal_result(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, commit_request = _prepared_commit(store, source_id)
    authority = AdministrativeMutationCAS(
        deployment_namespace=handoff_namespace,
        session_id=source_id,
        expected_stream_revision=operation.expected_source_stream_version,
    )
    abort_request = SessionHandoffAbortRequest(
        operation=operation,
        authority=authority,
        code="concurrent_abort",
    )

    def commit() -> object:
        try:
            return store.commit(commit_request)
        except Exception as error:  # pragma: no cover - assertion below reports the failure
            return error

    def abort() -> object:
        try:
            return store.abort_authorized(abort_request)
        except Exception as error:  # pragma: no cover - assertion below reports the failure
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        commit_result, abort_result = tuple(executor.map(lambda action: action(), (commit, abort)))

    successes = [
        result
        for result in (commit_result, abort_result)
        if not isinstance(result, Exception)
    ]
    assert len(successes) == 1
    status, abort_code = _operation_status(postgres_dsn, handoff_namespace, operation.operation_id)
    assert status in {"committed", "aborted"}
    if status == "aborted":
        assert abort_code == "concurrent_abort"
        assert _aggregate_counts(postgres_dsn, handoff_namespace) == {
            "committed_operations": 0,
            "envelopes": 0,
            "dispatches": 0,
            "child_streams": 0,
        }


def test_authorized_abort_keeps_namespace_and_source_identity_bound(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, _ = _prepared_commit(store, source_id)
    authority = AdministrativeMutationCAS(
        deployment_namespace=handoff_namespace,
        session_id=source_id,
        expected_stream_revision=operation.expected_source_stream_version,
    )
    with pytest.raises(HandoffStorageConflictError, match="authority"):
        store.abort_authorized(
            SessionHandoffAbortRequest(
                operation=operation,
                authority=authority.model_copy(update={"deployment_namespace": "other"}),
                code="wrong_namespace",
            )
        )
    assert _operation_status(postgres_dsn, handoff_namespace, operation.operation_id) == (
        "preparing",
        None,
    )


def test_abort_rolls_back_when_result_materialization_fails(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = _seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    store = _store(postgres_dsn, handoff_namespace)
    operation, _ = _prepared_commit(store, source_id)
    authority = AdministrativeMutationCAS(
        deployment_namespace=handoff_namespace,
        session_id=source_id,
        expected_stream_revision=operation.expected_source_stream_version,
    )
    request = SessionHandoffAbortRequest(
        operation=operation,
        authority=authority,
        code="injected_abort_failure",
    )
    def fail_after_update(row: object) -> object:
        raise RuntimeError("injected abort result failure")

    monkeypatch.setattr(authority_module, "operation_from_row", fail_after_update)
    with pytest.raises(RuntimeError, match="injected abort result failure"):
        store.abort_authorized(request)

    assert _operation_status(postgres_dsn, handoff_namespace, operation.operation_id) == (
        "preparing",
        None,
    )
