"""v95: extend derived cells for coverage; v64 and its checksum stay immutable."""

from agent_storage.postgres.migration_types import Migration

TASK_PROJECTION_COVERAGE_CELLS_MIGRATION = Migration(
    version=95,
    name="task_projection_coverage_cells",
    statements=(
        """ALTER TABLE task_projection_cells
            DROP CONSTRAINT task_projection_cells_cell_kind_check,
            DROP CONSTRAINT task_projection_cells_check1,
            ADD CONSTRAINT task_projection_cells_cell_kind_check CHECK(cell_kind IN (
                'text_message','text_ended','tool_call','interrupt','run_member','handoff','coverage')),
            ADD CONSTRAINT task_projection_cells_check1 CHECK(
                cell_kind IN ('text_message','handoff','coverage') OR value IS NULL OR value='1')
        """,
    ),
)
