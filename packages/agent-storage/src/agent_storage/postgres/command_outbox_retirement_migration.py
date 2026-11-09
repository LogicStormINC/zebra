"""Retire proven terminal fallback wakeups without publishing or deleting them."""

from agent_storage.postgres.migration_types import Migration

COMMAND_OUTBOX_RETIREMENT_MIGRATION = Migration(
    version=124,
    name="command_outbox_terminal_fallback_retirement",
    statements=(
        """ALTER TABLE broker_outbox DROP CONSTRAINT broker_outbox_status_check,
           ADD CONSTRAINT broker_outbox_status_check
           CHECK (status IN ('pending','publishing','published','dead','retired'))""",
        """CREATE FUNCTION retire_terminal_fallback_outbox(
               target_namespace text, target_scope text, batch_size integer
           ) RETURNS integer LANGUAGE plpgsql AS $retire$
           DECLARE retired_count integer;
           BEGIN
               IF current_setting('transaction_isolation') <> 'read committed' THEN
                   RAISE EXCEPTION USING ERRCODE='invalid_transaction_state',
                     MESSAGE='terminal fallback outbox retirement requires read committed';
               END IF;
               IF target_namespace IS NULL OR target_namespace = ''
                  OR target_scope IS NULL OR target_scope !~ '^[0-9a-f]{64}$'
                  OR batch_size IS NULL OR batch_size NOT BETWEEN 1 AND 128 THEN
                   RAISE EXCEPTION USING ERRCODE='invalid_parameter_value',
                     MESSAGE='invalid terminal fallback outbox batch';
               END IF;
               IF NOT pg_try_advisory_xact_lock(hashtextextended(
                   target_namespace || ':command-rollout:' || target_scope, 50
               )) THEN
                   RETURN 0;
               END IF;
               IF EXISTS (
                   SELECT 1 FROM command_delivery_scope_rollouts
                   WHERE deployment_namespace=target_namespace AND scope_key=target_scope
               ) THEN
                   RETURN 0;
               END IF;
               WITH candidates AS MATERIALIZED (
                   SELECT o.message_id
                   FROM broker_outbox o
                   JOIN session_command_pending p
                     ON (p.deployment_namespace,p.scope_key,p.command_id)
                      = (o.deployment_namespace,o.scope_key,o.operation_id)
                   JOIN command_handoff_receipts r
                     ON (r.deployment_namespace,r.scope_key,r.command_id,r.accepted_event_id)
                      = (p.deployment_namespace,p.scope_key,p.command_id,p.accepted_event_id)
                   JOIN broker_command_inbox i
                     ON (i.deployment_namespace,i.message_id)
                      = (o.deployment_namespace,o.message_id)
                   WHERE o.deployment_namespace=target_namespace AND o.scope_key=target_scope
                     AND o.status='pending' AND o.message_type='zebra.session.command.ready'
                     AND o.publish_attempts=0 AND o.relay_fence=0
                     AND o.relay_owner IS NULL AND o.lease_expires_at IS NULL
                     AND o.published_at IS NULL
                     AND p.origin='live' AND p.status='done'
                     AND o.wake_generation=p.current_generation AND o.aggregate_id=p.session_id
                     AND o.envelope_json->>'accepted_event_id'=p.accepted_event_id::text
                     AND r.status='accepted' AND r.wake_generation=o.wake_generation
                     AND r.session_id=p.session_id AND r.handled_event_id IS NOT NULL
                     AND i.status='accepted' AND i.envelope_digest=o.envelope_digest
                     AND (i.scope_key,i.command_id,i.accepted_event_id)
                       = (p.scope_key,p.command_id,p.accepted_event_id)
                   ORDER BY o.available_at,o.message_id LIMIT batch_size
                   FOR UPDATE OF o,p SKIP LOCKED
               )
               UPDATE broker_outbox o SET status='retired'
               FROM candidates
               WHERE o.deployment_namespace=target_namespace
                 AND o.message_id=candidates.message_id;
               GET DIAGNOSTICS retired_count = ROW_COUNT;
               RETURN retired_count;
           END;
           $retire$""",
    ),
)
