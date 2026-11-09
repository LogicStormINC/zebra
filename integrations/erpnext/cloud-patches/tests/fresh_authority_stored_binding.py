"""Assertion scenarios for fresh authority stored binding."""

from fresh_authority_fixtures import (
    BINDING,
    NOW,
    NS,
    REGISTRY,
    SID,
    TASK,
    UUID,
    Mock,
    Path,
    ast,
    fresh,
    patch,
)


def check_stored_binding(execution, SessionStatus):
    # Shared stored-binding validation: both native readers compare the same latest row's persisted
    # digest.

    SessionId = __import__("agent_core.domain.identifiers", fromlist=("SessionId",)).SessionId
    TaskId = __import__("agent_core.domain.identifiers", fromlist=("TaskId",)).TaskId
    task_admission = __import__(
        "agent_storage.postgres", fromlist=("task_admission",)
    ).task_admission
    IsolationLevel = __import__("psycopg", fromlist=("IsolationLevel",)).IsolationLevel

    class BindingConnection:
        def __init__(self, row):
            self.row = row
            self.queries = []
            self.isolation = None
            self.readonly = None

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "task_binding_snapshots" in sql:
                assert "SELECT binding_digest, snapshot_json FROM task_binding_snapshots" in sql
                assert "ORDER BY binding_revision DESC LIMIT 1" in sql
                assert "deployment_namespace=" in sql
                assert params is not None and "erpnext" in params
            return self

        def fetchone(self):
            return self.row

        def fetchall(self):
            return [self.row]

        def set_isolation_level(self, value):
            self.isolation = value

        def set_read_only(self, value):
            self.readonly = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    root = SessionId(UUID(TASK))

    def binding_row(digest=BINDING.binding_digest):
        return dict(
            root_session_id=TASK,
            snapshot_json=BINDING.model_dump(mode="json"),
            binding_digest=digest,
        )

    def bad_binding(call):
        try:
            call()
        except ValueError as error:
            assert "stored task binding digest" in str(error)
        else:
            raise AssertionError("invalid persisted binding digest accepted")

    for direct in (True, False):
        for digest in (
            BINDING.binding_digest,
            "0" * 64,
            None,
            42,
            b"a" * 64,
            "A" * 64,
            "g" * 64,
            "a" * 63,
            "a" * 65,
            "a" * 64 + "\n",
        ):
            row = binding_row(digest)
            if digest is None:
                row.pop("binding_digest")
            connection = BindingConnection(row)
            database = NS(
                connect=lambda *, connection=connection: connection,
                connect_task_io=lambda *, connection=connection: connection,
            )
            with (
                patch.object(task_admission, "PostgresDatabase", return_value=database),
                patch.object(task_admission, "root_for_session", return_value=root),
                patch.object(task_admission, "derive_lineage", return_value=[{"session_id": SID}]),
            ):

                def load(*, direct=direct):
                    if direct:
                        return task_admission.load_task_binding(
                            "unused", deployment_namespace="erpnext", task_id=TaskId(root)
                        )
                    return task_admission.load_session_task_binding(
                        "unused", deployment_namespace="erpnext", session_id=SID
                    )

                if digest == BINDING.binding_digest:
                    assert load() == BINDING
                else:
                    bad_binding(load)
            if direct:
                assert connection.queries[0][0] == "SET TRANSACTION READ ONLY"
            else:
                assert (
                    connection.isolation == IsolationLevel.REPEATABLE_READ
                    and connection.readonly is True
                )
    # Absence remains optional; existing lineage checks still fail closed.
    assert (
        task_admission._read_task_binding(BindingConnection(None), "erpnext", TaskId(root)) is None
    )
    with patch.object(task_admission, "derive_lineage", return_value=[]):
        try:
            task_admission.read_session_task_binding(
                BindingConnection(binding_row()), "erpnext", root
            )
        except ValueError as error:
            assert "native Task lineage" in str(error)
        else:
            raise AssertionError("missing lineage accepted")

    # Execute the actual composition closure, then the real fresh execution entry and shared loader
    # chain.
    loop_source = (
        Path(__file__).resolve().parents[1] / "overrides/apps/worker/src/zebra_agent_worker/loop.py"
    )
    loader_node = next(
        node
        for node in ast.walk(ast.parse(loop_source.read_text()))
        if isinstance(node, ast.FunctionDef) and node.name == "task_binding_loader"
    )
    loader_scope = dict(
        SessionId=SessionId,
        active_namespace="erpnext",
        binding_dsn="unused",
        _load_binding=task_admission.load_session_task_binding,
    )
    exec(
        compile(ast.Module(body=[loader_node], type_ignores=[]), str(loop_source), "exec"),
        loader_scope,
    )
    connection = BindingConnection(binding_row("0" * 64))
    completion_reader = Mock(side_effect=AssertionError("private completion payload read"))
    factory = NS(
        completion_reader=completion_reader,
        build=Mock(side_effect=AssertionError("private recorder constructed")),
    )
    service = NS(
        _erp_fresh_enabled=True,
        _erp_workspace_containment=None,
        _projection_recorder_factory=factory,
        _task_index_store=NS(task_id_for_session=lambda sid: TaskId(root)),
        _task_binding_loader=loader_scope["task_binding_loader"],
        _egress_registry=REGISTRY,
        _settings=NS(host_tool_shared_secret="test-only-hmac"),
    )
    claimed = NS(
        lease=NS(session_id=SID),
        recovery=NS(session=NS(status=SessionStatus.RUNNING), workspace=NS()),
    )
    with (
        patch.object(
            task_admission, "PostgresDatabase", return_value=NS(connect=lambda: connection)
        ),
        patch.object(fresh.FreshERPAuthority, "probe") as probe,
        patch.object(execution, "recover_execution_progress") as progress,
    ):
        bad_binding(
            lambda: execution.SessionExecutionService._execute_claimed_session_once(
                service, claimed, started_at=NOW, ownership_check=lambda: None
            )
        )
    probe.assert_not_called()
    completion_reader.assert_not_called()
    factory.build.assert_not_called()
    progress.assert_not_called()
    print(
        "PASS shared stored digest: both native readers, valid/mismatch/m"
        "issing/malformed, readonly/lineage, composed fresh loader 0 prob"
        "e/private recovery"
    )
