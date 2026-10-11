"""PostgreSQL composition of the native bounded Worker progress adapter."""

from agent_storage.worker_progress import WorkerProgressStoreMixin


class PostgresWorkerProgressMixin(WorkerProgressStoreMixin):
    _progress_postgres = True
