from pathlib import Path

import psycopg
from agent_storage import PostgresWorkspaceProjectionStore

import tests.agent_storage.test_postgres_session_handoffs as handoff_tests

pytest_plugins = ("tests.agent_storage.test_postgres_session_handoffs",)


def test_commit_preserves_the_workspace_binding_revision_for_child_recovery(
    postgres_dsn: str,
    handoff_namespace: str,
    tmp_path: Path,
) -> None:
    source_id = handoff_tests._seed_completed_source(postgres_dsn, handoff_namespace, tmp_path)
    workspaces = PostgresWorkspaceProjectionStore(
        postgres_dsn,
        deployment_namespace=handoff_namespace,
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE workspace_projections
            SET runtime_name = 'gvisor', runtime_engine = 'docker',
                runtime_image = %s, runtime_spec_digest = %s,
                runtime_network_enforcement = 'isolated',
                runtime_workspace_writable = true
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (
                "python@sha256:" + "a" * 64,
                "b" * 64,
                handoff_namespace,
                source_id,
            ),
        )
    store = handoff_tests._store(postgres_dsn, handoff_namespace)
    _, request = handoff_tests._prepared_commit(store, source_id)

    result = store.commit(request)

    child_workspace = workspaces.get_workspace(result.child_session_id)
    assert child_workspace is not None
    assert child_workspace.runtime_name == "gvisor"
    assert child_workspace.runtime_engine == "docker"
    assert child_workspace.runtime_spec_digest == "b" * 64
    assert (
        store.inspect_source_facts(result.child_session_id, at=handoff_tests.NOW).workspace_revision
        == request.envelope.workspace_revision
    )
