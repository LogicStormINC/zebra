"""Actual trusted volume resolver and Worker composition, without running its loop."""
import json
from pathlib import Path
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from zebra_agent_config import load_settings
from zebra_agent_worker.loop import build_worker_loop_service
from full_worker import compose


def main():
    cloud=cloud_composition_from_environment();settings=load_settings()
    if cloud.deployment_namespace!='erpnext-full' or 'native-db' not in cloud.dsn:
        raise ValueError('dedicated full QA only')
    state=json.loads(Path('/prepared.json').read_text())
    task_id=TaskId(UUID(state['task_id']))
    store=PostgresAgentTaskStore(cloud.dsn,deployment_namespace=cloud.deployment_namespace)
    task=store.get_task(task_id)
    assert task is not None and str(task.active_segment_id)==state['task']['session_id']
    composition=compose(settings,cloud)
    resolver=composition.workspace_resolver_factory()
    assert resolver is not None
    path=resolver.resolve(state['task']['workspace'],session_id=task.active_segment_id)
    assert path.name==state['task']['workspace'].split('//')[1] and path.is_mount()
    assert resolver.resolve_ready(state['task']['workspace'],session_id=task.active_segment_id)==path
    service=build_worker_loop_service(database_path=Path(settings.database_url),settings=settings,cloud_worker_composition=composition)
    assert service is not None  # Never call run()/execute_session(): provider is intentionally absent.
    for _ in range(8):
        if store.backfill_read_summary(task_id,limit=128,max_bytes=1048576):break
    assert store.read_task_summary(task_id).complete
    print(json.dumps(dict(stage='trusted_full_worker_composition',workspace=str(path),quota_bytes=256*1024*1024,
        allocation_allowed=True,ready_verification=True,worker_loop_run=False,model_calls=0,search_calls=0)))


if __name__=='__main__':main()
