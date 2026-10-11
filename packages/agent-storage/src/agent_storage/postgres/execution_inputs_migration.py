"""v74 additive exact execution-input frontier; apply only via explicit migration."""

from agent_storage.execution_inputs import execution_input_schema
from agent_storage.postgres.migration_types import Migration

EXECUTION_INPUTS_MIGRATION = Migration(
    version=74,
    name="bounded_fenced_execution_inputs",
    statements=execution_input_schema(postgres=True),
)
