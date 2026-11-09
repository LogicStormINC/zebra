"""Additive115; only explicit management commands ever close new admission."""

from agent_storage.postgres.migration_types import Migration

RUNTIME_GATE_MIGRATION = Migration(
    version=115,
    name="runtime_admission_gate",
    statements=(
        """
    CREATE TABLE runtime_namespace_gates( deployment_namespace text PRIMARY KEY
    REFERENCES control_plane_epochs, scope jsonb,revision bigint NOT NULL DEFAULT 0
    CHECK(revision>=0 AND revision<9007199254740992), mode text NOT NULL DEFAULT 'open'
    CHECK(mode IN ('open','draining')))
    """,
        """
    INSERT INTO runtime_namespace_gates(deployment_namespace) SELECT
    deployment_namespace FROM control_plane_epochs
    """,
        """
    CREATE FUNCTION runtime_gate_epoch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    INSERT INTO runtime_namespace_gates(deployment_namespace)
    VALUES(NEW.deployment_namespace); RETURN NEW; END $$
    """,
        """CREATE TRIGGER runtime_gate_epoch AFTER INSERT ON control_plane_epochs
 FOR EACH ROW EXECUTE FUNCTION runtime_gate_epoch()""",
        """CREATE TABLE runtime_gate_operations(
 deployment_namespace text NOT NULL REFERENCES runtime_namespace_gates,
 operation_id uuid NOT NULL,request jsonb NOT NULL,input_digest text NOT NULL,
 receipt jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(deployment_namespace,operation_id))""",
        """
    CREATE TABLE runtime_gate_worker_observations( deployment_namespace text NOT
    NULL,operation_id uuid NOT NULL,process_id uuid NOT NULL, fingerprint text NOT
    NULL,compatible boolean NOT NULL,reason text NOT NULL, expires_at timestamptz NOT
    NULL,epoch uuid NOT NULL,runtime_class text NOT NULL, PRIMARY
    KEY(deployment_namespace,operation_id,process_id), FOREIGN
    KEY(deployment_namespace,operation_id) REFERENCES runtime_gate_operations)
    """,
        """
    CREATE FUNCTION runtime_gate_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'runtime gate original is immutable'; END $$
    """,
        """
    CREATE TRIGGER runtime_gate_immutable BEFORE UPDATE OR DELETE ON
    runtime_gate_operations FOR EACH ROW EXECUTE FUNCTION runtime_gate_immutable()
    """,
        """
    CREATE FUNCTION runtime_gate_admission() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE gate_mode text; BEGIN IF NEW.event_type NOT IN
    ('session_created','user_message_received','session_command_accepted') THEN RETURN
    NEW; END IF; IF EXISTS(SELECT 1 FROM session_events e WHERE
    e.deployment_namespace=NEW.deployment_namespace AND e.event_id=NEW.event_id AND
    (e.session_id,e.sequence,e.event_type,e.actor,e.payload,e.created_at)=
    (NEW.session_id,NEW.sequence,NEW.event_type,NEW.actor,NEW.payload,NEW.created_at))
    THEN RETURN NEW; END IF; IF NEW.event_type='session_command_accepted' AND
    (NEW.payload->>'kind' IN ('cancel','stop','suspend') OR
    NEW.replay_internal_continuation) THEN RETURN NEW; END IF; SELECT mode INTO
    gate_mode FROM runtime_namespace_gates WHERE
    deployment_namespace=NEW.deployment_namespace FOR SHARE; IF gate_mode='draining'
    THEN RAISE EXCEPTION 'runtime admission draining' USING ERRCODE='55000'; END IF;
    RETURN NEW; END $$
    """,
        """CREATE TRIGGER zz_runtime_gate_admission BEFORE INSERT ON session_events
 FOR EACH ROW EXECUTE FUNCTION runtime_gate_admission()""",
        """
    CREATE INDEX runtime_gate_active_sessions ON
    session_projections(deployment_namespace,session_id) WHERE status NOT IN
    ('completed','failed','cancelled')
    """,
        """
    CREATE INDEX runtime_gate_task_metadata ON
    session_events(deployment_namespace,session_id,event_type,sequence DESC) WHERE
    event_type IN ('task_prepared','user_message_received')
    """,
        """
    CREATE INDEX runtime_gate_version_scopes ON
    agent_definition_bundle_versions(namespace_id)
    """,
    ),
)
