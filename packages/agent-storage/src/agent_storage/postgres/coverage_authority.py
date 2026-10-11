"""Post-lock fresh SQL boundaries for a previously verified Task lineage and binding."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.effect_dispatch import effect_input

from agent_storage.postgres.coverage_authority_migration import COVERAGE_AUTHORITY_MIGRATION
from agent_storage.postgres.database import PostgresDatabase


def lock_coverage_lease(
    connection: Any, namespace: str, session: SessionId,
) -> dict[str, Any] | None:
    """Epoch then lease pins; authority reads use a NEW post-lock SQL snapshot."""
    return cast(dict[str, Any] | None, connection.execute(
        """WITH epoch AS MATERIALIZED (
             SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE)
           SELECT l.*,e.epoch AS current_epoch FROM epoch e JOIN worker_leases l
             ON l.deployment_namespace=%s AND l.session_id=%s FOR SHARE OF l""",
        (namespace, namespace, session),
    ).fetchone())


def validate_coverage_lease(
    row: dict[str, Any] | None, fence: LeaseFence, now: datetime,
) -> None:
    from agent_storage.postgres.leases import _current

    if row is None or not _current(row, row["current_epoch"], fence, now):
        raise LeaseLostError("coverage execution lease boundary is no longer current")


class PostgresCoverageAuthority:
    def __init__(
        self, database: PostgresDatabase, session: SessionId, binding: TaskBindingSnapshot,
        versions: tuple[int, int], fence: LeaseFence,
    ) -> None:
        self.database, self.session, self.binding = database, session, binding
        self.versions, self.fence = versions, fence

    @classmethod
    def prepare(
        cls, database: PostgresDatabase, session: SessionId, binding: TaskBindingSnapshot,
        fence: LeaseFence, load_binding: Callable[[SessionId], TaskBindingSnapshot | None],
    ) -> "PostgresCoverageAuthority | None":
        # Read the version before independent lineage validation; changes during
        # preparation cannot qualify a stale context. No result survives a wake.
        versions = cls._versions(database, session, binding.task_id)
        if versions is None:
            return None
        current = load_binding(session)
        if current is None or effect_input(current) != effect_input(binding):
            raise ValueError("coverage execution Task binding changed during preparation")
        if cls._versions(database, session, binding.task_id) != versions:
            raise ValueError("coverage execution Task lineage changed during preparation")
        return cls(database, session, binding, versions, fence)

    @staticmethod
    def _versions(
        database: PostgresDatabase, session: SessionId, task: str,
    ) -> tuple[int, int] | None:
        with database.connect() as connection:
            qualified = connection.execute(
                "SELECT 1 FROM zebra_schema_migrations "
                "WHERE version=%s AND name=%s AND checksum=%s",
                (COVERAGE_AUTHORITY_MIGRATION.version, COVERAGE_AUTHORITY_MIGRATION.name,
                 COVERAGE_AUTHORITY_MIGRATION.checksum),
            ).fetchone()
            if qualified is None:
                return None
            rows = connection.execute(
                "SELECT session_id,revision FROM coverage_lineage_versions "
                "WHERE deployment_namespace=%s AND session_id=ANY(%s::uuid[])",
                (database.deployment_namespace, [str(session), task]),
            ).fetchall()
        indexed = {str(row["session_id"]): row["revision"] for row in rows}
        if str(session) not in indexed or task not in indexed:
            raise ValueError("coverage execution lineage version is missing")
        return indexed[str(session)], indexed[task]

    def check(self, *, deadline: datetime | None = None) -> int:
        """Fresh binding, active segment, STOP, epoch, lease and post-lock DB time.

        Lease writes retain their native transactional fence. This short read
        ends before any object/model/Host request; no connection crosses I/O.
        """
        namespace = self.database.deployment_namespace
        with self.database.connect() as connection:
            lease = lock_coverage_lease(connection, namespace, self.session)
            row = self._read_lineage(connection)
            validate_coverage_lease(lease, self.fence, row["now"])
        return self._validate_lineage(row, deadline)

    def check_lineage(self, *, deadline: datetime | None = None) -> int:
        """Read-only recovery authority; NEVER grants a lease or mutation right.

        Exceptional recovery still verifies its independent history and native
        command fence. Only repeated unchanged lineage traversal is substituted.
        """
        with self.database.connect() as connection:
            row = self._read_lineage(connection)
        return self._validate_lineage(row, deadline)

    def _read_lineage(self, connection: Any) -> dict[str, Any]:
        row = connection.execute(
                """SELECT clock_timestamp() AS now,
                     (SELECT current_version FROM session_streams
                       WHERE deployment_namespace=l.deployment_namespace
                         AND session_id=l.session_id) AS current_version,
                     (SELECT status FROM session_projections
                       WHERE deployment_namespace=l.deployment_namespace
                         AND session_id=l.session_id) AS status,
                     (SELECT active_segment_id FROM agent_tasks
                       WHERE deployment_namespace=l.deployment_namespace AND task_id=%s)
                         AS active_segment_id,
                     (SELECT revision FROM coverage_lineage_versions
                       WHERE deployment_namespace=l.deployment_namespace
                         AND session_id=l.session_id) AS session_revision,
                     (SELECT revision FROM coverage_lineage_versions
                       WHERE deployment_namespace=l.deployment_namespace AND session_id=%s)
                         AS task_revision,
                     (SELECT snapshot_json FROM task_binding_snapshots
                       WHERE deployment_namespace=l.deployment_namespace AND task_id=%s
                       ORDER BY binding_revision DESC LIMIT 1) AS snapshot_json,
                     EXISTS(SELECT 1 FROM session_events stop
                       WHERE stop.deployment_namespace=l.deployment_namespace
                         AND stop.session_id=l.session_id AND (
                           stop.event_type IN
                             ('session_cancelled','session_failed','session_completed')
                           OR (stop.event_type='session_command_accepted'
                               AND stop.payload->>'kind' IN ('stop','cancel')))) AS stopped
                   FROM (SELECT %s::text AS deployment_namespace,%s::uuid AS session_id) l""",
                (*([self.binding.task_id] * 3), self.database.deployment_namespace, self.session),
            ).fetchone()
        assert row is not None  # Scalar SELECT has exactly one result row.
        return cast(dict[str, Any], row)

    def _validate_lineage(self, row: dict[str, Any], deadline: datetime | None) -> int:
        host = self.binding.host_capability
        expiry = host.grant_expires_at
        if host.host_context is None or host.host_context.expires_at is None or expiry is None:
            raise ValueError("coverage execution authority is missing an expiry")
        deadline = min(expiry, host.host_context.expires_at, deadline or expiry)
        if (
            (row["session_revision"], row["task_revision"]) != self.versions
            or row["snapshot_json"] != self.binding.model_dump(mode="json")
            or str(row["active_segment_id"]) != str(self.session)
            or row["status"] not in {"ready", "running"}
            or row["stopped"]
            or (deadline is not None and row["now"] >= deadline)
        ):
            raise ValueError("coverage execution authority changed or expired")
        return int(row["current_version"])
