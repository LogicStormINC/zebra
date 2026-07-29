from collections.abc import Callable

from agent_core.domain.leases import WorkerLease
from agent_core.domain.sessions import Session
from agent_core.domain.workspaces import WorkspaceProjection
from agent_core.ports import (
    WorkerMutationAuthority,
    WorkerProjectionTransactionPort,
)
from agent_storage import ControlPlaneStores

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer


class WorkerProjectionRecorderFactory:
    def __init__(
        self,
        *,
        stores: ControlPlaneStores,
        model_call_indexer: ModelCallIndexer,
        tool_run_indexer: ToolRunIndexer,
        transaction: WorkerProjectionTransactionPort | None,
        deployment_namespace: str | None,
    ) -> None:
        if (transaction is None) != (deployment_namespace is None):
            raise ValueError(
                "worker projection transaction and deployment namespace must be configured together"
            )
        self._stores = stores
        self._model_call_indexer = model_call_indexer
        self._tool_run_indexer = tool_run_indexer
        self._transaction = transaction
        self._deployment_namespace = deployment_namespace

    def build(
        self,
        *,
        session: Session,
        workspace: WorkspaceProjection,
        lease: WorkerLease,
        ownership_check: Callable[[], None],
    ) -> DurableHarnessEventRecorder:
        authority = (
            None
            if self._deployment_namespace is None
            else WorkerMutationAuthority(
                deployment_namespace=self._deployment_namespace,
                session_id=lease.session_id,
                lease_fence=lease.fence,
                expected_stream_revision=session.current_sequence,
            )
        )
        return DurableHarnessEventRecorder(
            session=session,
            workspace=workspace,
            event_store=self._stores.events,
            projection_store=self._stores.sessions,
            workspace_store=self._stores.workspaces,
            model_call_indexer=self._model_call_indexer,
            tool_run_indexer=self._tool_run_indexer,
            ownership_check=ownership_check,
            worker_projection_transaction=self._transaction,
            worker_mutation_authority=authority,
        )
