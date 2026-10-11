"""v93: seal exact manifest membership, advance only unique Event-backed parts."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_MEMBERSHIP_MIGRATION = Migration(
    version=93,
    name="coverage_exact_membership_seal",
    statements=(
        "ALTER TABLE coverage_units ADD COLUMN record JSONB",
        """CREATE TABLE coverage_membership_seals (
           deployment_namespace TEXT NOT NULL,namespace TEXT NOT NULL,run_id TEXT NOT NULL,
           session_id UUID NOT NULL,binding JSONB NOT NULL,manifest_event UUID NOT NULL,
           expected_count BIGINT NOT NULL CHECK(expected_count>=0),
           expected_digest TEXT NOT NULL,target_chain TEXT NOT NULL,chain TEXT NOT NULL,
           record_count BIGINT NOT NULL,records_seeded BIGINT NOT NULL DEFAULT 0,
           target_records_chain TEXT NOT NULL,records_chain TEXT NOT NULL,
           seeded BIGINT NOT NULL DEFAULT 0,part_count BIGINT NOT NULL DEFAULT 0,
           remaining_parts BIGINT NOT NULL DEFAULT 0,sealed BOOLEAN NOT NULL DEFAULT FALSE,
           invalidated BOOLEAN NOT NULL DEFAULT FALSE,
           PRIMARY KEY(deployment_namespace,namespace,run_id))""",
        """CREATE TABLE coverage_membership_parts (
           deployment_namespace TEXT NOT NULL,namespace TEXT NOT NULL,run_id TEXT NOT NULL,
           unit_digest TEXT NOT NULL,unit_key JSONB NOT NULL,reservation_key TEXT,
           settled BOOLEAN NOT NULL DEFAULT FALSE,
           PRIMARY KEY(deployment_namespace,namespace,run_id,unit_digest),
           CONSTRAINT coverage_membership_reservation
             UNIQUE(deployment_namespace,namespace,run_id,reservation_key))""",
        """CREATE TABLE coverage_membership_records (
           deployment_namespace TEXT NOT NULL,namespace TEXT NOT NULL,run_id TEXT NOT NULL,
           record_id TEXT NOT NULL,ordinal BIGINT NOT NULL,record JSONB NOT NULL,
           PRIMARY KEY(deployment_namespace,namespace,run_id,record_id),
           UNIQUE(deployment_namespace,namespace,run_id,ordinal))""",
        # ponytail: MD5 is only a fixed-size index candidate; exact JSONB equality
        # remains mandatory. It grants no digest/semantic proof and avoids wide keys.
        """CREATE INDEX coverage_membership_part_key ON coverage_membership_parts
           (deployment_namespace,namespace,run_id,
            (md5(unit_key::text)))""",
        """CREATE FUNCTION guard_coverage_membership() RETURNS trigger
           LANGUAGE plpgsql AS $$ BEGIN
             IF pg_trigger_depth()<2 OR TG_OP IN ('DELETE','TRUNCATE') THEN
               RAISE EXCEPTION 'coverage membership is database maintained';
             END IF;
             IF TG_TABLE_NAME='coverage_membership_seals' AND TG_OP='UPDATE' THEN
               IF (
               (NEW.deployment_namespace,NEW.namespace,NEW.run_id,NEW.session_id,
                NEW.binding,NEW.manifest_event,
                NEW.expected_count,NEW.expected_digest,NEW.target_chain,NEW.record_count,
                NEW.target_records_chain) IS DISTINCT FROM
               (OLD.deployment_namespace,OLD.namespace,OLD.run_id,OLD.session_id,
                OLD.binding,OLD.manifest_event,
                OLD.expected_count,OLD.expected_digest,OLD.target_chain,OLD.record_count,
                OLD.target_records_chain)
               OR (OLD.invalidated AND NOT NEW.invalidated)) THEN
                 RAISE EXCEPTION 'coverage membership identity cannot reset';
               END IF;
             END IF;
             RETURN NEW;
           END $$""",
        *tuple(
            f"""CREATE TRIGGER coverage_membership_guard BEFORE INSERT OR UPDATE OR DELETE
                ON {table} FOR EACH ROW EXECUTE FUNCTION guard_coverage_membership()"""
            for table in ("coverage_membership_seals", "coverage_membership_parts",
                          "coverage_membership_records")
        ),
        *tuple(
            f"""CREATE TRIGGER coverage_membership_no_truncate BEFORE TRUNCATE
                ON {table} FOR EACH STATEMENT EXECUTE FUNCTION guard_coverage_membership()"""
            for table in ("coverage_membership_seals", "coverage_membership_parts",
                          "coverage_membership_records")
        ),
        """CREATE FUNCTION advance_coverage_membership() RETURNS trigger
           LANGUAGE plpgsql AS $$ DECLARE
             body JSONB;previous JSONB;scope JSONB;dep TEXT;ns TEXT;run TEXT;
             facts coverage_membership_seals;descriptor JSONB;source JSONB;
             next_chain TEXT;next_records_chain TEXT;valid BOOLEAN;changed BIGINT;record JSONB;
           BEGIN
             IF TG_OP='TRUNCATE' THEN
               UPDATE coverage_membership_seals SET invalidated=TRUE; RETURN NULL;
             END IF;
             IF TG_OP<>'INSERT' THEN previous=to_jsonb(OLD); END IF;
             IF TG_OP<>'DELETE' THEN body=to_jsonb(NEW); END IF;
             IF TG_TABLE_NAME='session_events' AND TG_OP='INSERT'
                 AND body->>'event_type'='coverage_manifest_committed' THEN
               descriptor=body->'payload'->'membership';
               IF descriptor->>'schema'='coverage-membership/1'
                   AND descriptor->>'chain' ~ '^[0-9a-f]{64}$'
                   AND descriptor->>'expected_digest' ~ '^[0-9a-f]{64}$'
                   AND descriptor->>'records_chain' ~ '^[0-9a-f]{64}$'
                   AND descriptor->'record_count'=
                     body->'payload'->'binding'->'snapshot'->'record_count'
                   AND descriptor->'expected_count'=body->'payload'->'expected_count' THEN
                 dep=body->>'deployment_namespace';ns=body->'payload'->>'namespace';
                 run=body->'payload'->>'run_id';
                 INSERT INTO coverage_membership_seals
                   (deployment_namespace,namespace,run_id,session_id,binding,manifest_event,
                    expected_count,expected_digest,target_chain,chain,sealed,invalidated,
                    record_count,target_records_chain,records_chain)
                 VALUES(dep,ns,run,(body->>'session_id')::uuid,body->'payload'->'binding',
                   (body->>'event_id')::uuid,(descriptor->>'expected_count')::bigint,
                   descriptor->>'expected_digest',descriptor->>'chain',
                   encode(sha256(convert_to('coverage-membership/1','UTF8')),'hex'),
                   (descriptor->>'expected_count')::bigint=0,
                   EXISTS(SELECT 1 FROM coverage_runs WHERE deployment_namespace=dep
                     AND namespace=ns AND run_id=run),
                   (descriptor->>'record_count')::bigint,descriptor->>'records_chain',
                   encode(sha256(convert_to('coverage-membership-records/1','UTF8')),'hex'))
                 ON CONFLICT(deployment_namespace,namespace,run_id)
                   DO UPDATE SET invalidated=TRUE;
               ELSE
                 UPDATE coverage_membership_seals SET invalidated=TRUE WHERE
                   deployment_namespace=body->>'deployment_namespace'
                   AND namespace=body->'payload'->>'namespace'
                   AND run_id=body->'payload'->>'run_id';
               END IF;
               RETURN NULL;
             END IF;
             IF TG_TABLE_NAME='session_events'
                 AND body->>'event_type' IS DISTINCT FROM 'coverage_manifest_committed'
                 AND previous->>'event_type' IS DISTINCT FROM 'coverage_manifest_committed' THEN
               RETURN NULL;
             END IF;
             FOR scope IN SELECT DISTINCT jsonb_build_array(value->>'deployment_namespace',
                 CASE WHEN TG_TABLE_NAME='session_events' THEN value->'payload'->>'namespace'
                   ELSE value->>'namespace' END,
                 CASE WHEN TG_TABLE_NAME='session_events' THEN value->'payload'->>'run_id'
                   ELSE value->>'run_id' END) FROM unnest(ARRAY[previous,body]) s(value)
                 WHERE value IS NOT NULL AND (TG_TABLE_NAME<>'session_events'
                   OR value->>'event_type'='coverage_manifest_committed') LOOP
               dep=scope->>0;ns=scope->>1;run=scope->>2;
               SELECT * INTO facts FROM coverage_membership_seals WHERE
                 deployment_namespace=dep AND namespace=ns AND run_id=run FOR UPDATE;
               IF NOT FOUND OR facts.invalidated THEN CONTINUE; END IF;
               valid=FALSE;
               IF TG_TABLE_NAME='coverage_runs' THEN
                 valid=TG_OP<>'DELETE' AND body->'binding'=facts.binding
                   AND body->>'session_id'=facts.session_id::text;
               ELSIF TG_TABLE_NAME='coverage_units' THEN
                 IF TG_OP='INSERT' AND NOT facts.sealed
                     AND (body->>'ordinal')::bigint=facts.seeded
                     AND facts.seeded<facts.expected_count THEN
                   next_chain=encode(sha256(convert_to(facts.chain || jsonb_build_array(
                     body->'unit_key'->>'record_id',body->'unit_key'->>'content_digest',
                     body->'unit_key'->>'check_id',body->'unit_key'->>'check_version',
                     body->'unit_key'->>'definition_digest',body->'unit_key'->>'kind',
                     body->'unit_key'->>'part_id',body->'unit_key'->>'part_digest')::text,
                     'UTF8')),'hex');
                   valid=TRUE;
                   IF body->'record'<>'null'::jsonb THEN
                     record=body->'record';
                     IF (record->>'ordinal')::bigint<>facts.records_seeded
                         OR record->>'record_id'<>body->'unit_key'->>'record_id'
                         OR record->>'content_digest'<>body->'unit_key'->>'content_digest' THEN
                       valid=FALSE;
                     ELSE
                       SELECT encode(sha256(convert_to(facts.records_chain || jsonb_build_array(
                         (record->>'ordinal')::bigint,record->>'record_id',record->>'content_digest',
                         (SELECT jsonb_agg(jsonb_build_array(p->>'id',p->>'kind',p->>'digest',
                           (p->>'byte_length')::bigint) ORDER BY ord)
                           FROM jsonb_array_elements(record->'parts') WITH ORDINALITY r(p,ord))
                         )::text,'UTF8')),'hex') INTO next_records_chain;
                       INSERT INTO coverage_membership_records
                         VALUES(dep,ns,run,record->>'record_id',(record->>'ordinal')::bigint,record);
                       UPDATE coverage_membership_seals SET records_seeded=records_seeded+1,
                         records_chain=next_records_chain WHERE
                         deployment_namespace=dep AND namespace=ns AND run_id=run;
                       facts.records_seeded=facts.records_seeded+1;
                       facts.records_chain=next_records_chain;
                     END IF;
                   END IF;
                   IF body->'unit_key'->>'kind'='part' THEN
                     INSERT INTO coverage_membership_parts
                       (deployment_namespace,namespace,run_id,unit_digest,unit_key)
                     VALUES(dep,ns,run,body->>'unit_digest',body->'unit_key');
                   END IF;
                   UPDATE coverage_membership_seals SET seeded=seeded+1,chain=next_chain,
                     part_count=part_count+
                       CASE WHEN body->'unit_key'->>'kind'='part' THEN 1 ELSE 0 END,
                     remaining_parts=remaining_parts+
                       CASE WHEN body->'unit_key'->>'kind'='part' THEN 1 ELSE 0 END,
                     sealed=seeded+1=expected_count AND next_chain=target_chain
                       AND records_seeded=record_count AND records_chain=target_records_chain,
                     invalidated=NOT valid OR (seeded+1=expected_count AND (
                       next_chain<>target_chain OR records_seeded<>record_count
                       OR records_chain<>target_records_chain))
                     WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
                 ELSIF TG_OP='UPDATE' THEN
                   valid=(previous-'result')=(body-'result');
                 END IF;
               ELSIF TG_TABLE_NAME='coverage_model_calls' AND facts.sealed THEN
                 SELECT to_jsonb(e) INTO source FROM session_events e WHERE
                   deployment_namespace=dep AND session_id=facts.session_id
                   AND sequence=(body->>'reserved_sequence')::bigint;
                 valid=TG_OP<>'DELETE' AND source->>'event_type'='coverage_model_call_reserved'
                   AND source->'payload'->>'namespace'=ns AND source->'payload'->>'run_id'=run
                   AND source->'payload'->'reservation'=body->'reservation';
                 IF TG_OP='INSERT' AND valid THEN
                   UPDATE coverage_membership_parts SET reservation_key=body->>'reservation_key'
                     WHERE deployment_namespace=dep AND namespace=ns AND run_id=run
                       AND md5(unit_key::text)=md5((body->'reservation'->'key')::text)
                       AND unit_key=body->'reservation'->'key' AND reservation_key IS NULL;
                   GET DIAGNOSTICS changed=ROW_COUNT;valid=changed=1;
                 ELSIF TG_OP='UPDATE' AND valid AND (previous-'receipt'-'receipt_sequence')=
                     (body-'receipt'-'receipt_sequence') AND previous->'receipt'='null'::jsonb
                     AND body->'receipt'<>'null'::jsonb THEN
                   SELECT to_jsonb(e) INTO source FROM session_events e WHERE
                     deployment_namespace=dep AND session_id=facts.session_id
                     AND sequence=(body->>'receipt_sequence')::bigint;
                   valid=source->>'event_type'='coverage_model_usage_recorded'
                     AND source->'payload'->>'namespace'=ns AND source->'payload'->>'run_id'=run
                     AND source->'payload'->'receipt'=body->'receipt';
                   IF valid THEN
                     UPDATE coverage_membership_parts SET settled=TRUE WHERE
                       deployment_namespace=dep AND namespace=ns AND run_id=run
                       AND unit_key=body->'reservation'->'key' AND NOT settled
                       AND reservation_key=body->>'reservation_key';
                     GET DIAGNOSTICS changed=ROW_COUNT;valid=changed=1;
                     IF valid THEN
                       UPDATE coverage_membership_seals SET remaining_parts=remaining_parts-1
                         WHERE deployment_namespace=dep AND namespace=ns AND run_id=run;
                     END IF;
                   END IF;
                 ELSE valid=FALSE;
                 END IF;
               END IF;
               IF valid IS DISTINCT FROM TRUE THEN
                 UPDATE coverage_membership_seals SET invalidated=TRUE WHERE
                   deployment_namespace=dep AND namespace=ns AND run_id=run;
               END IF;
             END LOOP;
             RETURN NULL;
           END $$""",
        *tuple(
            f"""CREATE TRIGGER coverage_membership_source_{table}
                AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW
                EXECUTE FUNCTION advance_coverage_membership()"""
            for table in ("session_events", "coverage_runs", "coverage_units",
                          "coverage_model_calls")
        ),
        *tuple(
            f"""CREATE TRIGGER coverage_membership_truncate_{table}
                AFTER TRUNCATE ON {table} FOR EACH STATEMENT
                EXECUTE FUNCTION advance_coverage_membership()"""
            for table in ("session_events", "coverage_runs", "coverage_units",
                          "coverage_model_calls")
        ),
    ),
)
