"""v75 additive indexed evidence-boundary admission for execution-input v3."""

from agent_storage.execution_inputs import execution_input_compaction_schema
from agent_storage.postgres.migration_types import Migration

EXECUTION_INPUT_COMPACTION_MIGRATION = Migration(
    version=75,
    name="execution_input_evidence_boundaries",
    statements=execution_input_compaction_schema(postgres=True),
)
