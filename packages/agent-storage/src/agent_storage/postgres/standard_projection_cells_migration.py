"""v116: independent standard-profile derived state; source history is unchanged."""

from agent_storage.postgres.migration_types import Migration

STANDARD_PROJECTION_CELLS_MIGRATION = Migration(
    version=116,
    name="standard_projection_cells",
    statements=(
        """ALTER TABLE task_projection_cells
            DROP CONSTRAINT task_projection_cells_cell_kind_check,
            DROP CONSTRAINT task_projection_cells_check1,
            ADD CONSTRAINT task_projection_cells_cell_kind_check CHECK(cell_kind IN (
                'text_message','text_ended','tool_call','interrupt','run_member','handoff',
                'coverage','standard_v1')),
            ADD CONSTRAINT task_projection_cells_check1 CHECK(
                cell_kind IN ('text_message','handoff','coverage','standard_v1')
                OR value IS NULL OR value='1')
        """,
    ),
)
