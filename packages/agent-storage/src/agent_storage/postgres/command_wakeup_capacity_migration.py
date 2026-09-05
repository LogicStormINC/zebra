"""v49: bounded command admission pressure."""

from agent_storage.postgres.migration_types import Migration

COMMAND_CAPACITY_MIGRATION = Migration(
    version=49,
    name="command_admission_capacity",
    statements=(
        """ALTER TABLE command_wakeup_rollouts
           ADD COLUMN max_pending_per_scope INTEGER NOT NULL DEFAULT 32
               CHECK (max_pending_per_scope BETWEEN 1 AND 1000),
           ADD COLUMN max_pending_control_per_scope INTEGER NOT NULL DEFAULT 8
               CHECK (max_pending_control_per_scope BETWEEN 1 AND 100),
           ADD COLUMN max_unpublished_outbox INTEGER NOT NULL DEFAULT 10000
               CHECK (max_unpublished_outbox BETWEEN 1 AND 1000000),
           ADD COLUMN reserved_control_outbox INTEGER NOT NULL DEFAULT 64
               CHECK (reserved_control_outbox BETWEEN 0 AND 10000)""",
        """ALTER TABLE command_wakeup_rollouts
           ADD CONSTRAINT command_control_outbox_reserve_bounded
           CHECK (reserved_control_outbox < max_unpublished_outbox)""",
        "ALTER TABLE session_command_pending ADD COLUMN scope_sequence BIGINT",
        """WITH ranked AS (
               SELECT deployment_namespace, accepted_event_id,
                      row_number() OVER (
                          PARTITION BY deployment_namespace, scope_key
                          ORDER BY created_at, accepted_event_id
                      ) AS value
               FROM session_command_pending
           ) UPDATE session_command_pending pending SET scope_sequence=ranked.value
             FROM ranked WHERE pending.deployment_namespace=ranked.deployment_namespace
               AND pending.accepted_event_id=ranked.accepted_event_id""",
        """ALTER TABLE session_command_pending ALTER COLUMN scope_sequence SET NOT NULL,
           ADD CONSTRAINT session_command_scope_sequence_positive CHECK (scope_sequence > 0)""",
        """CREATE FUNCTION assign_command_scope_sequence() RETURNS trigger AS $$
           DECLARE
             rollout command_wakeup_rollouts%ROWTYPE;
             unpublished BIGINT;
             scope_pending BIGINT;
             is_control BOOLEAN;
             rollout_active BOOLEAN;
             existing session_command_pending%ROWTYPE;
             outbox_exists BOOLEAN;
             outbox_ceiling INTEGER;
             scope_ceiling INTEGER;
           BEGIN
             IF NEW.scope_sequence IS NULL THEN
               SELECT * INTO rollout FROM command_wakeup_rollouts
                 WHERE deployment_namespace=NEW.deployment_namespace FOR SHARE;
               rollout_active := FOUND AND rollout.admission_enabled;
               IF rollout_active THEN
                 PERFORM pg_advisory_xact_lock(hashtextextended(
                   NEW.deployment_namespace || ':command-global', 49));
               END IF;
               PERFORM pg_advisory_xact_lock(hashtextextended(
                 NEW.deployment_namespace || ':command-scope:' || NEW.scope_key, 49));
               SELECT * INTO existing FROM session_command_pending
                 WHERE deployment_namespace=NEW.deployment_namespace
                   AND scope_key=NEW.scope_key AND command_id=NEW.command_id;
               IF FOUND THEN
                 IF (existing.accepted_event_id, existing.session_id,
                     existing.accepted_sequence, existing.tenant_id, existing.workspace_id)
                    IS DISTINCT FROM
                    (NEW.accepted_event_id, NEW.session_id, NEW.accepted_sequence,
                     NEW.tenant_id, NEW.workspace_id) THEN
                   RAISE EXCEPTION USING ERRCODE='unique_violation',
                     MESSAGE='command_pending_identity_conflict';
                 END IF;
                 NEW.scope_sequence := existing.scope_sequence;
                 SELECT EXISTS (
                   SELECT 1 FROM broker_outbox
                   WHERE deployment_namespace=NEW.deployment_namespace
                     AND scope_key=NEW.scope_key AND operation_id=NEW.command_id
                     AND message_type='zebra.session.command.ready' AND wake_generation=0
                 ) INTO outbox_exists;
                 IF outbox_exists THEN
                   RETURN NEW;
                 END IF;
               END IF;
               IF rollout_active THEN
                 is_control := NEW.command_kind IN ('cancel','stop','suspend');
                 outbox_ceiling := CASE WHEN is_control
                   THEN rollout.max_unpublished_outbox
                   ELSE rollout.max_unpublished_outbox - rollout.reserved_control_outbox END;
                 SELECT count(*) INTO unpublished FROM broker_outbox
                   WHERE deployment_namespace=NEW.deployment_namespace
                     AND status IN ('pending','publishing');
                 IF unpublished >= outbox_ceiling THEN
                   RAISE EXCEPTION USING ERRCODE='check_violation',
                     MESSAGE='command_outbox_capacity';
                 END IF;
                 IF NEW.origin='live' AND existing.command_id IS NULL THEN
                   scope_ceiling := CASE WHEN is_control
                     THEN rollout.max_pending_control_per_scope
                     ELSE rollout.max_pending_per_scope END;
                   SELECT count(*) INTO scope_pending FROM session_command_pending
                     WHERE deployment_namespace=NEW.deployment_namespace
                       AND scope_key=NEW.scope_key AND status='pending'
                       AND (command_kind IN ('cancel','stop','suspend'))=is_control;
                   IF scope_pending >= scope_ceiling THEN
                     RAISE EXCEPTION USING ERRCODE='check_violation',
                       MESSAGE='command_scope_capacity';
                   END IF;
                 END IF;
               END IF;
               IF existing.command_id IS NULL THEN
                 SELECT COALESCE(MAX(scope_sequence),0)+1 INTO NEW.scope_sequence
                   FROM session_command_pending
                   WHERE deployment_namespace=NEW.deployment_namespace
                     AND scope_key=NEW.scope_key;
               END IF;
             END IF;
             RETURN NEW;
           END;
           $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER assign_command_scope_sequence_before_insert
           BEFORE INSERT ON session_command_pending FOR EACH ROW
           EXECUTE FUNCTION assign_command_scope_sequence()""",
        """CREATE UNIQUE INDEX session_command_scope_sequence
           ON session_command_pending (deployment_namespace, scope_key, scope_sequence)""",
        """CREATE INDEX command_pending_execution_fair_pickup
           ON session_command_pending (
             deployment_namespace, scope_sequence, created_at, accepted_event_id
           ) WHERE status='pending' AND command_kind IN ('run','resume','message')""",
        """CREATE INDEX command_pending_control_fair_pickup
           ON session_command_pending (
             deployment_namespace, scope_sequence, created_at, accepted_event_id
           ) WHERE status='pending' AND command_kind IN ('cancel','stop','suspend')""",
        """CREATE INDEX command_pending_execution_scope_head
           ON session_command_pending (
             deployment_namespace, scope_key, scope_sequence, created_at, accepted_event_id
           ) WHERE status='pending' AND command_kind IN ('run','resume','message')""",
        """CREATE INDEX command_pending_control_scope_head
           ON session_command_pending (
             deployment_namespace, scope_key, scope_sequence, created_at, accepted_event_id
           ) WHERE status='pending' AND command_kind IN ('cancel','stop','suspend')""",
    ),
)
