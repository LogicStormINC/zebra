"""ERP deployment composition only; all execution remains in generic cloud-agent."""
from pathlib import Path

import httpx
from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.connection_pool import postgres_pool_scope
from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore
from zebra_agent_config import load_settings
from zebra_agent_worker.cloud_composition import compose_cloud_worker
from zebra_agent_worker.loop import build_worker_loop_service
from full_workspace_client import PrivateWorkspaceClient, ROOT


def compose(settings, cloud):
    if (settings.storage_authority!='postgresql' or settings.deployment!='cloud'
            or cloud.deployment_namespace!='erpnext-full' or not settings.host_execution_authority.enabled
            or not settings.runtime.require_workspace_quota):
        raise ValueError('full runtime requires native storage, fresh authority and physical quota')
    client=PrivateWorkspaceClient()
    store=PostgresWorkspaceControlStore(cloud.dsn,deployment_namespace=cloud.deployment_namespace)
    def require(wid,sid,*,allocate):
        instance=store.get(wid)
        if instance is None: raise ValueError('unknown workspace')
        return client.require(sid,instance,allow_allocate=allocate)
    def verify(wid,sid,path):
        if path!=ROOT/str(wid) or require(wid,sid,allocate=False)!=path:
            raise ValueError('workspace resolver path mismatch')
    return compose_cloud_worker(cloud,memory_settings=settings.memory_gateway,
        prepare_workspace_volume=lambda wid,sid:require(wid,sid,allocate=True),
        verify_workspace_volume=verify)


def main():
    settings=load_settings()
    cloud=cloud_composition_from_environment()
    with postgres_pool_scope(settings.database_url), httpx.Client(
            timeout=httpx.Timeout(60,connect=10),trust_env=False) as model_client:
        service=build_worker_loop_service(database_path=Path(settings.database_url),settings=settings,
            cloud_worker_composition=compose(settings,cloud),model_http_client=model_client)
        service.run(worker_id='erpnext-full-worker',batch_size=1,lease_ttl_seconds=30,
            max_cycles=None,stop_when_idle=False,idle_sleep_seconds=.5)


if __name__=='__main__': main()
