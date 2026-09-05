"""Read-only cutover checks and bounded canonical scope discovery for maintenance."""

from agent_storage.postgres.command_wakeup_discovery import PendingCursor
from agent_storage.postgres.command_wakeup_pickup import (
    PickupLane,
    PickupScopeMode,
    discover_command_pickups,
    resolve_command_pickup,
)
from agent_storage.postgres.command_wakeup_recovery import recover_command_batch
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.migrations import MIGRATIONS


def command_cutover_state(dsn: str, namespace: str, *, require_ready: bool = False) -> bool:
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        exists = connection.execute(
            "SELECT to_regclass('command_wakeup_rollouts') AS name"
        ).fetchone()
        if exists is None or exists["name"] is None:
            if require_ready:
                raise ValueError("command delivery requires operator migration and cutover")
            return False
        row = connection.execute(
            """SELECT admission_enabled,
            COALESCE(to_jsonb(rollout)->>'backfill_state','not_started') AS backfill_state
            FROM command_wakeup_rollouts rollout
            WHERE deployment_namespace=%s""",
            (namespace,),
        ).fetchone()
        migrated = row is not None and (
            row["admission_enabled"] or row["backfill_state"] != "not_started"
        )
        if not migrated:
            migrated = (
                connection.execute(
                    """SELECT 1 FROM session_command_pending
                WHERE deployment_namespace=%s LIMIT 1""",
                    (namespace,),
                ).fetchone()
                is not None
            )
        if migrated or require_ready:
            applied = {
                r["version"]: r
                for r in connection.execute(
                    "SELECT version,name,checksum FROM zebra_schema_migrations"
                ).fetchall()
            }
            if any(
                m.version not in applied
                or (applied[m.version]["name"], applied[m.version]["checksum"])
                != (m.name, m.checksum)
                for m in MIGRATIONS
            ):
                raise ValueError("command delivery requires the complete verified schema")
        if require_ready and not migrated:
            raise ValueError("command delivery requires explicit operator cutover")
        return bool(migrated)


class CommandRecoverySweep:
    def __init__(
        self,
        dsn: str,
        namespace: str,
        batch_size: int,
        *,
        scope_mode: PickupScopeMode = "all",
    ) -> None:
        self._dsn, self._namespace, self._batch = dsn, namespace, batch_size
        if scope_mode not in ("all", "fallback"):
            raise ValueError("invalid recovery scope mode")
        self._scope_mode = scope_mode
        self._cursors: dict[PickupLane, PendingCursor | None] = {"execution": None, "control": None}

    def tick(self) -> None:
        scopes = set()
        for lane in ("execution", "control"):
            rows = discover_command_pickups(
                self._dsn,
                deployment_namespace=self._namespace,
                lane=lane,
                batch_size=self._batch,
                after=self._cursors[lane],
                scope_mode=self._scope_mode,
            )
            if not rows:
                self._cursors[lane] = None
            for row in rows:
                try:
                    resolved = resolve_command_pickup(
                        self._dsn,
                        deployment_namespace=self._namespace,
                        accepted_event_id=row.accepted_event_id,
                    )
                except ValueError:
                    # Invalid hints remain quarantine responsibility; advance this bounded page.
                    self._cursors[lane] = row.cursor
                    continue
                if resolved.scope not in scopes:
                    recover_command_batch(
                        self._dsn,
                        deployment_namespace=self._namespace,
                        scope=resolved.scope,
                        batch_size=self._batch,
                    )
                    scopes.add(resolved.scope)
                self._cursors[lane] = row.cursor
