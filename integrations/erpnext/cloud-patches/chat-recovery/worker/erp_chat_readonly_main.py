"""Native ERP chat/query consumer only; no general Worker maintenance or old work."""
from datetime import UTC, datetime
from pathlib import Path
import time
from threading import Event, Thread

import httpx
from agent_storage.postgres.connection_pool import postgres_pool_scope
from agent_storage.postgres.erp_chat_readonly import enabled
from zebra_agent_config import load_settings
from zebra_agent_worker.command_process_state import command_cutover_state
from zebra_agent_worker.erp_fresh_authority import FreshERPAuthority, require_early_authority
from zebra_agent_worker.loop import build_worker_loop_service


def require_native105_schema(applied, migrations):
    expected = {(m.version, m.name, m.checksum) for m in migrations if m.version <= 105}
    if not expected or max(row[0] for row in expected) != 105 or set(applied) != expected:
        raise ValueError('ERP readonly chat requires the exact native105 schema')


def run_chat_projection(loop, stop):
    """Only scalar-selected new-generation Tasks enter native derived projection."""
    from agent_core.domain.identifiers import TaskId
    from agent_storage.postgres.erp_chat_readonly import candidate_sql
    policy = loop._execution_service._erp_workspace_containment
    service = loop._projection_work
    if service is None:
        raise ValueError('native chat projection service required')
    cursors, repaired, after_task, enabled_consumers = {}, {}, None, set()

    def require_new_task(task_id):
        with policy._database.connect_task_io() as connection:
            connection.execute('SET TRANSACTION READ ONLY')
            row = connection.execute(
                'SELECT p.session_id FROM agent_tasks t JOIN session_projections p '
                'ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id '
                'WHERE t.deployment_namespace=%s AND t.task_id=%s ' + candidate_sql('p'),
                ('erpnext', task_id)).fetchone()
        if row is None:
            return False  # Old Tasks never enter a body read, repair, defer or ACK.
        policy.require(row['session_id'])
        return True

    while not stop.is_set():
        try:
            with policy._database.connect_task_io() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                rows = connection.execute(
                    'SELECT t.task_id,t.next_event_sequence FROM agent_tasks t JOIN session_projections p '
                    'ON p.deployment_namespace=t.deployment_namespace AND p.session_id=t.active_segment_id '
                    'WHERE t.deployment_namespace=%s AND (%s::uuid IS NULL OR t.task_id>%s::uuid) '
                    + candidate_sql('p') + ' ORDER BY t.task_id LIMIT 32',
                    ('erpnext', after_task, after_task)).fetchall()
            after_task = rows[-1]['task_id'] if rows else None
            for consumer in service.consumers:
                if id(consumer) not in enabled_consumers:
                    consumer.work.enable_projection_work()  # Config only; no global bootstrap.
                    enabled_consumers.add(id(consumer))
                for row in rows:
                    key = (id(consumer), row['task_id'])
                    if repaired.get(key) != row['next_event_sequence'] and require_new_task(row['task_id']):
                        # Native105 appends maintain canonical metadata; only route derived work here.
                        if not consumer.work.repair_projection_work(TaskId(row['task_id']), limit=256).needs_repair:
                            repaired[key] = row['next_event_sequence']
                pending = consumer.work.read_pending_projection_work(limit=32, after_scope=cursors.get(id(consumer)))
                cursors[id(consumer)] = pending[-1].scope if pending else None
                for work in pending:
                    if require_new_task(work.scope.task_id):
                        consumer.materialize_once(work)
            # ponytail: at most512 scalar HWM cache entries; eviction only repeats
            # native routing repair. A native Task-filtered work port can replace this scan.
            while len(repaired) > 512:
                repaired.pop(next(iter(repaired)))
        except Exception as error:
            print('erp_chat_projection_deferred:' + type(error).__name__, flush=True)
        stop.wait(0.5)


def main():
    settings = load_settings()
    if not enabled('erpnext') or settings.deployment != 'cloud':
        raise ValueError('explicit cloud ERP readonly chat mode required')
    if (settings.client_integration_enabled or settings.mcp_servers or settings.mcp_credentials.worker_enabled
            or settings.cloud_extension_worker_enabled or settings.cloud_skill_worker_enabled
            or settings.cloud_extensions_read_enabled or settings.cloud_extensions_manage_enabled
            or settings.cloud_extension_turn_admission_enabled or settings.cloud_skills_publish_enabled or settings.plugins.enabled
            or settings.memory_gateway.enabled or settings.session_handoff.enabled
            or settings.skill_roots or settings.skill_roots_system or settings.skill_roots_admin or settings.skill_roots_repo
            or settings.command_delivery.publish_enabled or settings.command_delivery.consume_enabled):
        raise ValueError('ERP readonly chat cannot enable optional execution capabilities')
    if command_cutover_state(settings.database_url, 'erpnext'):
        raise ValueError('ERP readonly chat requires the existing unmigrated command lane')
    # Verify the unchanged native105 ledger. HTTP attachment migration106 is
    # deliberately not used by this zero-Artifact path; never alter the catalog.
    import psycopg
    from agent_storage.postgres.migrations import MIGRATIONS
    with psycopg.connect(settings.database_url) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        applied = connection.execute('SELECT version,name,checksum FROM zebra_schema_migrations').fetchall()
    require_native105_schema(applied, MIGRATIONS)
    with postgres_pool_scope(settings.database_url), httpx.Client(timeout=httpx.Timeout(60, connect=10), trust_env=False) as model_client:
        loop = build_worker_loop_service(database_path=Path(settings.database_url), settings=settings, model_http_client=model_client)
        consumer = loop._command_consumer
        execution = loop._execution_service
        if (consumer is None or consumer._command_reader is None or execution._workspace_resolver is not None
                or execution._cloud_artifact_factory is not None or execution._client_runtime is not None
                or loop._projection_work is None):
            raise ValueError('ERP readonly chat native composition mismatch')
        original_reader = consumer._command_reader

        def read_command(session_id, revision):
            policy = execution._erp_workspace_containment
            policy.require(session_id)
            # Control selection is scalar-kind filtered; never load a RUN/MESSAGE
            # body to decide whether Fresh may be bypassed for STOP/CANCEL.
            from agent_core.domain.events import SessionEvent
            from agent_storage.postgres.legacy_command_candidates import _UNREJECTED, LEGACY_REJECTION_ACTION
            with policy._database.connect_task_io() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                control = connection.execute(
                    f"SELECT e.* FROM session_events e WHERE e.deployment_namespace=%s AND e.session_id=%s "
                    f"AND e.sequence>%s AND e.event_type='session_command_accepted' "
                    f"AND e.payload->>'kind' IN ('stop','cancel') AND {_UNREJECTED} ORDER BY e.sequence LIMIT 1",
                    ('erpnext', session_id, revision, LEGACY_REJECTION_ACTION)).fetchone()
            if control is not None:
                return SessionEvent.model_validate(control)
            require_early_authority(FreshERPAuthority.for_execution(execution, session_id).probe(datetime.now(UTC)))
            return original_reader(session_id, revision)

        consumer._command_reader = read_command
        projection_stop = Event()
        projection_thread = Thread(target=run_chat_projection, args=(loop, projection_stop), name='erp-chat-projection', daemon=True)
        projection_thread.start()
        # ponytail: use the existing native consumer/ExecutionService, never
        # loop.run/poll_once: those also maintain unrelated historical work.
        while True:
            try:
                result = consumer.consume_once(worker_id='erp-chat-readonly', lease_ttl_seconds=60, batch_size=1)
                for session in loop._projection_store.list_ready_sessions(limit=1):
                    if str(session.session_id) != result.session_id:
                        execution.execute_session(session.session_id, worker_id='erp-chat-readonly', lease_ttl_seconds=60)
            except Exception as error:
                # Native errors retain native state; never log messages, credentials or bodies.
                print('erp_chat_readonly_deferred:' + type(error).__name__, flush=True)
            time.sleep(0.5)


if __name__ == '__main__':
    main()
