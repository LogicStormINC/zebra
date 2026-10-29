"""Explicit bounded derived-summary preparation on the migrated QA clone only."""
import json
import os
from pathlib import Path

import psycopg
from agent_core.domain.identifiers import TaskId
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from check_capability_upgrade import read_inventory, require_isolated


def main():
    dsn = os.environ['ERP_CAPABILITY_QA_DSN']
    require_isolated(dsn)
    output = Path(os.environ['ERP_CAPABILITY_QA_OUTPUT'])
    if output.exists():
        raise ValueError('Refusing to replace earlier maintenance evidence')
    definitions, before = read_inventory(dsn)
    with psycopg.connect(dsn) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        rows = connection.execute("SELECT task_id FROM agent_tasks "
            "WHERE deployment_namespace='erpnext' ORDER BY task_id LIMIT 101").fetchall()
    assert len(rows) <= 100
    store = PostgresAgentTaskStore(dsn, deployment_namespace='erpnext')
    pages = 0
    for identity, in rows:
        for _ in range(256):
            pages += 1
            if store.backfill_read_summary(TaskId(identity), limit=256, max_bytes=1048576):
                break
        else:
            raise ValueError('Bounded summary preparation incomplete; retain frontier')
        assert store.read_task_summary(TaskId(identity)).complete
    _, after = read_inventory(dsn, definitions)
    changed = [table for table in before if before[table] != after[table]]
    allowed = {'task_read_summary_heads', 'task_read_summary_frontiers', 'task_attachment_index'}
    result = {'tasks': len(rows), 'bounded_pages': pages, 'max_page_bytes': 1048576,
        'changed_derived_tables': changed, 'canonical_unchanged': set(changed) <= allowed,
        'model_calls': 0, 'search_calls': 0, 'worker_started': False}
    output.write_text(json.dumps(result, indent=2)+'\n')
    output.chmod(0o600)
    assert result['canonical_unchanged'], changed
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
