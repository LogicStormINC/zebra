"""v50: scoped broker rollout and physically separate command shadow evidence."""

from agent_storage.postgres.migration_types import Migration

COMMAND_ROLLOUT_SHADOW_MIGRATION = Migration(
    version=50,
    name="command_rollout_shadow",
    statements=(
        """ALTER TABLE command_wakeup_rollouts
           ADD COLUMN max_unpublished_shadow INTEGER NOT NULL DEFAULT 1000
             CHECK (max_unpublished_shadow BETWEEN 1 AND 100000)""",
        """CREATE TABLE command_delivery_scope_rollouts (
             deployment_namespace TEXT NOT NULL,
             scope_key TEXT NOT NULL CHECK (scope_key ~ '^[0-9a-f]{64}$'),
             mode TEXT NOT NULL CHECK (mode IN ('broker','shadow')),
             actor TEXT NOT NULL CHECK (length(btrim(actor)) BETWEEN 1 AND 128),
             reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
             updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             PRIMARY KEY (deployment_namespace,scope_key)
           )""",
        """CREATE TABLE command_delivery_scope_rollout_audit (
             change_id BIGSERIAL PRIMARY KEY,
             deployment_namespace TEXT NOT NULL,
             scope_key TEXT NOT NULL CHECK (scope_key ~ '^[0-9a-f]{64}$'),
             previous_mode TEXT CHECK (previous_mode IN ('broker','shadow')),
             new_mode TEXT CHECK (new_mode IN ('broker','shadow')),
             actor TEXT NOT NULL CHECK (length(btrim(actor)) BETWEEN 1 AND 128),
             reason TEXT NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
             changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             CHECK (previous_mode IS DISTINCT FROM new_mode)
           )""",
        """CREATE TABLE command_shadow_outbox (
             deployment_namespace TEXT NOT NULL,
             shadow_message_id UUID NOT NULL,
             source_message_id UUID NOT NULL,
             scope_key TEXT NOT NULL CHECK (scope_key ~ '^[0-9a-f]{64}$'),
             envelope_digest TEXT NOT NULL CHECK (envelope_digest ~ '^[0-9a-f]{64}$'),
             status TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','publishing','published','dead')),
             relay_owner TEXT,
             relay_fence BIGINT NOT NULL DEFAULT 0 CHECK (relay_fence >= 0),
             lease_expires_at TIMESTAMPTZ,
             publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
             available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             published_at TIMESTAMPTZ,
             created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             PRIMARY KEY (deployment_namespace,shadow_message_id),
             UNIQUE (deployment_namespace,source_message_id)
           )""",
        """CREATE INDEX command_shadow_outbox_pending
           ON command_shadow_outbox (deployment_namespace,available_at,shadow_message_id)
           WHERE status IN ('pending','publishing')""",
        """CREATE TABLE command_shadow_observations (
             deployment_namespace TEXT NOT NULL,
             consumer_role TEXT NOT NULL CHECK (consumer_role='command-shadow-v1'),
             shadow_message_id UUID NOT NULL,
             source_message_id UUID NOT NULL,
             scope_key TEXT NOT NULL CHECK (scope_key ~ '^[0-9a-f]{64}$'),
             envelope_digest TEXT NOT NULL CHECK (envelope_digest ~ '^[0-9a-f]{64}$'),
             observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             PRIMARY KEY (deployment_namespace,consumer_role,shadow_message_id),
             UNIQUE (deployment_namespace,consumer_role,source_message_id)
           )""",
        """CREATE TABLE command_shadow_rejections (
             deployment_namespace TEXT NOT NULL,
             consumer_role TEXT NOT NULL CHECK (consumer_role='command-shadow-v1'),
             body_digest TEXT NOT NULL CHECK (body_digest ~ '^[0-9a-f]{64}$'),
             rejection_code TEXT NOT NULL CHECK (rejection_code='invalid_shadow_envelope'),
             observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
             PRIMARY KEY (deployment_namespace,consumer_role,body_digest)
           )""",
    ),
)
