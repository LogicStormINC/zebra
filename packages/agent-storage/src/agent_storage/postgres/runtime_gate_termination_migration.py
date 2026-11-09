"""Additive116: retain original gate termination proofs and late-submit fences."""

from agent_storage.postgres.migration_types import Migration

RUNTIME_GATE_TERMINATION_MIGRATION = Migration(
    version=116,
    name="runtime_gate_original_termination",
    statements=(
        """CREATE TABLE runtime_gate_terminations(
 deployment_namespace text NOT NULL REFERENCES runtime_namespace_gates,
 termination_id uuid NOT NULL,operation_id uuid NOT NULL,
 request jsonb NOT NULL,input_digest text NOT NULL,receipt jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(deployment_namespace,termination_id),
 UNIQUE(deployment_namespace,operation_id))""",
        """CREATE TRIGGER runtime_gate_termination_immutable BEFORE UPDATE OR DELETE ON
 runtime_gate_terminations FOR EACH ROW EXECUTE FUNCTION runtime_gate_immutable()""",
    ),
)
