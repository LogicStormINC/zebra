"""Index exact executor start receipt prefixes independently of locale."""

from agent_storage.postgres.migration_types import Migration

FORCE_STOP_RECEIPT_INDEX_MIGRATION = Migration(
    version=126,
    name="force_stop_executor_receipt_prefix_index",
    statements=(
        """CREATE INDEX force_stop_executor_started_prefix
           ON control_plane_idempotency_records
              (deployment_namespace, idempotency_key text_pattern_ops)
           WHERE action='executor_started'""",
    ),
)
