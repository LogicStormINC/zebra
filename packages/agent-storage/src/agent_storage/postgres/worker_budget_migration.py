"""Additive v121: Task-wide ordinary Worker budget and immutable wire receipts."""

from agent_storage.postgres.migration_types import Migration

WORKER_BUDGET_MIGRATION = Migration(
    version=121,
    name="worker_task_budget",
    statements=(
        """CREATE TABLE worker_task_budgets (
          deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
          binding_digest TEXT NOT NULL CHECK(length(binding_digest)=64),
          started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
          deadline TIMESTAMPTZ NOT NULL,
          last_session_id UUID NOT NULL, last_fence JSONB NOT NULL,
          last_attempt BIGINT NOT NULL CHECK(last_attempt>0),
          max_model_tokens BIGINT NOT NULL CHECK(max_model_tokens>=0),
          max_tool_calls BIGINT NOT NULL CHECK(max_tool_calls>=0),
          charged_tokens BIGINT NOT NULL DEFAULT 0 CHECK(charged_tokens>=0),
          tool_calls BIGINT NOT NULL DEFAULT 0 CHECK(tool_calls>=0),
          PRIMARY KEY(deployment_namespace,task_id),
          CHECK(charged_tokens<=max_model_tokens), CHECK(tool_calls<=max_tool_calls)
        )""",
        """CREATE TABLE worker_model_reservations (
          deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL,
          reservation_id UUID NOT NULL, request_digest TEXT NOT NULL,
          session_id UUID NOT NULL, attempt_number BIGINT NOT NULL,
          fence JSONB NOT NULL, input_upper BIGINT NOT NULL, output_cap BIGINT NOT NULL,
          counter_contract TEXT NOT NULL, receipt JSONB,
          PRIMARY KEY(deployment_namespace,task_id,reservation_id),
          FOREIGN KEY(deployment_namespace,task_id)
            REFERENCES worker_task_budgets(deployment_namespace,task_id)
        )""",
        """CREATE UNIQUE INDEX worker_unknown_request ON worker_model_reservations
          (deployment_namespace,task_id,request_digest) WHERE receipt IS NULL""",
        """CREATE UNIQUE INDEX worker_provider_receipt ON worker_model_reservations
          (deployment_namespace,task_id,(receipt->>'id')) WHERE receipt IS NOT NULL""",
        """CREATE TABLE worker_tool_reservations (
          deployment_namespace TEXT NOT NULL, task_id UUID NOT NULL, call_id UUID NOT NULL,
          PRIMARY KEY(deployment_namespace,task_id,call_id),
          FOREIGN KEY(deployment_namespace,task_id)
            REFERENCES worker_task_budgets(deployment_namespace,task_id)
        )""",
    ),
)
