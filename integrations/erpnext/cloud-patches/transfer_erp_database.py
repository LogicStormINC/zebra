#!/usr/bin/env python3
"""Fail-closed, offline ERP105 namespace transfer. No infrastructure/cutover commands.

Host: inspect CONFIG; transfer CONFIG --approved FILE --fingerprint SHA256.
Worker: private NDJSON protocol; invoked only by the host in the pinned API image.
See ERP_DATABASE_TRANSFER.md. Successful transfer never activates a consumer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import uuid

NAMESPACES = ('erpnext', 'erpnext-history', 'erpnext-continuation')
DEFINITION = ('erpnext', 'https://erpnext.zebra.local')
PG_IMAGE = 'sha256:5d004e058f520673f1f6edbad6b1603d5dab4c818e257c041889ef64672a8cc4'
API_IMAGE = 'sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef'
SOURCE_CONTAINER = 'zebra-dependencies-postgres-1'
SOURCE_DATABASE = SOURCE_ROLE = 'zebra'
SOURCE_NETWORK = 'zebra-dependencies'
CONSUMERS = ('erpnext-agent-api-1', 'erpnext-agent-worker-1')
TABLES = '''active_context_projections
agent_definition_draft_validations
agent_definition_drafts
agent_definition_eval_evidence
agent_definition_records
agent_definition_versions
agent_mailbox_messages
agent_release_records
agent_tasks
artifact_payload_management_audit
artifact_payload_metadata
artifact_payload_mutations
broker_command_inbox
broker_control_inbox
broker_outbox
client_control_leases
client_effect_continuations
client_effect_receipts
client_effects
client_mounted_capability_snapshots
client_run_bindings
client_sessions
command_control_receipts
command_coverage_requirements
command_delivery_rejections
command_delivery_scope_rollout_audit
command_delivery_scope_rollouts
command_handoff_receipts
command_recovery_attempts
command_retirement_operations
command_retirements
command_runtime_cleanup
command_shadow_observations
command_shadow_outbox
command_shadow_rejections
command_wakeup_rollouts
completion_gate_receipts
context_capsule_artifacts
control_plane_cutovers
control_plane_delivery_audit_records
control_plane_epochs
control_plane_idempotency_records
coverage_batches
coverage_continuations
coverage_execution_receipts
coverage_lineage_versions
coverage_membership_parts
coverage_membership_records
coverage_membership_seals
coverage_model_calls
coverage_model_events
coverage_model_ledger
coverage_model_revisions
coverage_model_summary
coverage_runs
coverage_task_summary
coverage_units
delivery_transactions
direct_control_operations
effect_outbox
execution_input_heads
execution_segments
extension_configuration_revisions
extension_configurations
frontend_capability_bindings
frontend_capability_profiles
governed_memory_operations
governed_memory_records
governed_memory_scan_items
governed_memory_scan_snapshots
handoff_dispatch_outbox
handoff_operations
host_authority_registries
host_connector_bindings
host_connector_profiles
host_grant_audit
host_grant_replay_ledger
host_manifest_freezes
mcp_catalog_versions
mcp_credential_versions
memory_delivery_operations
memory_delivery_scopes
memory_provider_mappings
model_call_projections
native_memory_authority
native_memory_operations
native_memory_retrieval
native_memory_scopes
orchestration_dependencies
orchestration_nodes
orchestration_plan_revisions
orchestration_result_bundles
orchestration_runs
provider_continuation_artifacts
provider_continuation_management_audit
provider_continuation_mutations
runtime_instances
schedule_authority_bindings
session_command_pending
session_command_read_heads
session_events
session_handoff_envelopes
session_observation_headers
session_projections
session_recovery_frontiers
session_streams
skill_package_upload_keys
skill_package_versions
subagent_delegation_links
task_attachment_index
task_binding_snapshots
task_event_index
task_projection_blocks
task_projection_cells
task_projection_frames
task_projection_heads
task_projection_scalars
task_projection_source_heads
task_projection_work
task_projection_work_projectors
task_projection_work_routes
task_read_summary_frontiers
task_read_summary_heads
task_schedule_firings
task_schedules
tool_run_projections
turn_extension_snapshots
user_personalization_settings
worker_leases
worker_process_capabilities
worker_progress_heads
worker_progress_outputs
worker_progress_receipts
workspace_control_instances
workspace_control_operations
workspace_control_snapshots
workspace_projections
zebra_schema_migrations'''.split()
ROUTINES = '''advance_coverage_lineage_versions
advance_coverage_membership
advance_coverage_model_position_volume
advance_coverage_model_revision
advance_coverage_model_summary
advance_coverage_model_volume
advance_coverage_task_summary
allocate_task_event_position
assign_command_scope_sequence
check_command_coverage_commit
compute_event_byte_bound
compute_projection_source_metadata
compute_replay_header
coverage_model_event_source
delete_session_observation_header
derive_session_observation_header
guard_coverage_lineage_versions
guard_coverage_membership
guard_coverage_model_revision
guard_coverage_model_summary
guard_coverage_task_summary
guard_projection_block_coordinate
guard_task_event_business
guard_task_event_reservation
guard_task_event_source
invalidate_coverage_model_volume
record_projection_source_assignment
reject_coverage_execution_receipt_mutation
reject_session_handoff_envelope_mutation
retain_coverage_execution_source
route_task_projection_work
seal_coverage_execution_source
task_replay_coverage_marker
wake_projection_work_task
write_projection_source_metadata'''.split()
TRIGGERS = [tuple(pair.split(':')) for pair in '''agent_tasks:agent_tasks_projection_work_insert
artifact_payload_metadata:coverage_model_volume_metadata
artifact_payload_metadata:coverage_model_volume_truncate
command_coverage_requirements:command_coverage_commit
coverage_execution_receipts:coverage_execution_receipt_source_seal
coverage_execution_receipts:coverage_execution_receipts_append_only
coverage_execution_receipts:coverage_execution_receipts_no_truncate
coverage_lineage_versions:coverage_lineage_versions_guard
coverage_lineage_versions:coverage_lineage_versions_no_truncate
coverage_membership_parts:coverage_membership_guard
coverage_membership_parts:coverage_membership_no_truncate
coverage_membership_records:coverage_membership_guard
coverage_membership_records:coverage_membership_no_truncate
coverage_membership_seals:coverage_membership_guard
coverage_membership_seals:coverage_membership_no_truncate
coverage_model_calls:coverage_membership_source_coverage_model_calls
coverage_model_calls:coverage_membership_truncate_coverage_model_calls
coverage_model_calls:coverage_model_revision_coverage_model_calls
coverage_model_calls:coverage_model_revision_truncate_coverage_model_calls
coverage_model_calls:coverage_model_summary_coverage_model_calls
coverage_model_calls:coverage_model_summary_truncate_coverage_model_calls
coverage_model_calls:coverage_model_volume_calls
coverage_model_events:coverage_model_revision_coverage_model_events
coverage_model_events:coverage_model_revision_truncate_coverage_model_events
coverage_model_events:coverage_model_summary_coverage_model_events
coverage_model_events:coverage_model_summary_truncate_coverage_model_events
coverage_model_ledger:coverage_model_revision_coverage_model_ledger
coverage_model_ledger:coverage_model_revision_truncate_coverage_model_ledger
coverage_model_ledger:coverage_model_summary_coverage_model_ledger
coverage_model_ledger:coverage_model_summary_truncate_coverage_model_ledger
coverage_model_revisions:coverage_model_revision_guard
coverage_model_revisions:coverage_model_revision_no_truncate
coverage_model_summary:coverage_model_summary_guard
coverage_model_summary:coverage_model_summary_no_truncate
coverage_runs:coverage_membership_source_coverage_runs
coverage_runs:coverage_membership_truncate_coverage_runs
coverage_task_summary:coverage_task_summary_guard
coverage_task_summary:coverage_task_summary_no_truncate
coverage_units:coverage_membership_source_coverage_units
coverage_units:coverage_membership_truncate_coverage_units
session_command_pending:assign_command_scope_sequence_before_insert
session_events:coverage_execution_source_no_truncate
session_events:coverage_execution_source_retention
session_events:coverage_lineage_events
session_events:coverage_lineage_events_truncate
session_events:coverage_membership_source_session_events
session_events:coverage_membership_source_update
session_events:coverage_membership_truncate_session_events
session_events:coverage_model_position_volume
session_events:coverage_model_revision_session_events
session_events:coverage_model_revision_source_update
session_events:coverage_model_revision_truncate_session_events
session_events:coverage_model_summary_session_events
session_events:coverage_model_summary_source_update
session_events:coverage_model_summary_truncate_session_events
session_events:coverage_model_volume_source
session_events:coverage_task_summary_events
session_events:coverage_task_summary_events_truncate
session_events:session_events_allocate_task_position
session_events:session_events_byte_bound
session_events:session_events_projection_assignment
session_events:session_events_projection_coordinate
session_events:session_events_projection_metadata
session_events:session_events_projection_work_assign
session_events:session_events_projection_work_insert
session_events:session_events_scalar_header
session_events:session_events_source_append_order
session_events:session_events_task_business_immutable
session_events:session_events_task_positions_immutable
session_events:session_events_task_source_delete
session_handoff_envelopes:session_handoff_envelopes_immutable
session_projections:coverage_lineage_projections
session_projections:coverage_lineage_projections_truncate
session_projections:session_observation_header_delete
session_projections:session_observation_header_write
task_binding_snapshots:coverage_lineage_bindings
task_binding_snapshots:coverage_lineage_bindings_truncate
task_event_index:task_event_reservation_guard'''.split()]
DEFINITIONS = set('agent_definition_draft_validations agent_definition_drafts agent_definition_eval_evidence agent_definition_records agent_definition_versions agent_release_records'.split())
SEQUENCE_OWNERS = {('command_delivery_scope_rollout_audit', 'change_id'),
                   ('control_plane_delivery_audit_records', 'audit_id'),
                   ('host_grant_audit', 'audit_id'), ('mcp_catalog_versions', 'publication_sequence')}
SESSION_SETTINGS = "SET client_encoding='UTF8'; SET timezone='UTC'; SET datestyle='ISO, YMD'; SET extra_float_digits=3; SET bytea_output='hex'; SET intervalstyle='postgres'; SET search_path=public,pg_catalog; SET statement_timeout='15min'; SET lock_timeout='10s'"


class Refusal(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refusal(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def secure_read(path):
    p = Path(path).absolute()
    parent = p.parent.lstat()
    require(stat.S_ISDIR(parent.st_mode) and stat.S_IMODE(parent.st_mode)==0o700 and parent.st_uid==os.geteuid(),'protected_directory_mode')
    fd = os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o600,'protected_file_mode')
        require(info.st_uid==os.geteuid(),'protected_file_owner')
        return source.read()


def secure_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)


def next_sequence(seq, maximum):
    require(seq['start'] == 1 and seq['increment'] == 1 and not seq['cycle'] and seq['min'] <= 1 <= seq['max'], 'sequence_parameters')
    if maximum is None:
        return seq['start'], False
    value = max(seq['start'], maximum)
    require(seq['min'] <= value < seq['max'], 'sequence_exhausted')
    return value, True



def canonical_migrations():
    # Import immutable installed definitions only; never run a migration/bootstrap.
    from agent_storage.postgres.migrations import MIGRATIONS
    expected = sorted((m.version,m.name,m.checksum) for m in MIGRATIONS)
    require(len(expected)==104 and expected[-1][:2]==(105,'scoped_plugin_installations') and len({r[0] for r in expected})==104,'pinned_native_catalog_not105')
    return expected


def validate_ledger(rows, expected=None):
    expected = canonical_migrations() if expected is None else expected
    require([tuple(r) for r in rows]==[tuple(r) for r in expected],'source_ledger_not_canonical105')


def classify(table):
    name = table['name']
    require(name in TABLES, 'unknown_relation')
    columns = {c['name'] for c in table['columns']}
    if name == 'zebra_schema_migrations':
        require('deployment_namespace' not in columns, 'ledger_scope')
        return 'ledger'
    if name in DEFINITIONS:
        require({'namespace_id', 'authority_issuer'} <= columns and 'deployment_namespace' not in columns, 'definition_scope')
        return 'definition'
    require('deployment_namespace' in columns, 'unclassified_relation')
    return 'deployment'


def validate_catalog(m):
    require([t['name'] for t in m['tables']] == TABLES, 'relation_inventory')
    require(len(m['views']) == 1 and m['views'][0]['name'] == 'task_replay_coverage_privacy' and m['views'][0]['definition'], 'view_inventory')
    require(not m['other_relations'] and not m['policies'] and not m['user_types'], 'unknown_schema_object')
    require([r['name'] for r in m['routines']] == ROUTINES and not any(r['security_definer'] for r in m['routines']), 'routine_inventory')
    require([(t['table'],t['name']) for t in m['triggers']] == TRIGGERS, 'trigger_inventory')
    generated = []
    for table in m['tables']:
        classify(table)
        require(table['kind'] == 'r' and not table['partition'] and table['pk'], 'table_shape')
        require(not table['rls'] and not table['force_rls'], 'unexpected_rls')
        require(len(table['pk']) == len(set(table['pk'])) and set(table['pk']) <= {c['name'] for c in table['columns']}, 'primary_key')
        generated.extend((table['name'], c['name'], c['generated']) for c in table['columns'] if c['generated'])
    require(generated == [('governed_memory_records', 'search_vector', 's')], 'generated_inventory')
    require(len(m['sequences']) == 4 and {(s['table'], s['column']) for s in m['sequences']} == SEQUENCE_OWNERS, 'sequence_inventory')
    for sequence in m['sequences']:
        next_sequence(sequence, None)
    require(m['extensions'] == [{'name': 'plpgsql', 'version': '1.0'}], 'extensions')
    require(all(c['validated'] for c in m['constraints']) and all(i['valid'] and i['ready'] for i in m['indexes']), 'invalid_schema')


# Catalog definitions are owner/OID independent, so native restore can be compared exactly.
CATALOG_SQL = r"""
SELECT jsonb_build_object(
 'tables', (SELECT jsonb_agg(jsonb_build_object('name',c.relname,'kind',c.relkind,'partition',c.relispartition,'persistence',c.relpersistence,'replica_identity',c.relreplident,'options',c.reloptions,'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,
   'columns',(SELECT jsonb_agg(jsonb_build_object('name',a.attname,'number',a.attnum,'type',format_type(a.atttypid,a.atttypmod),'notnull',a.attnotnull,'default',pg_get_expr(d.adbin,d.adrelid),'generated',a.attgenerated,'identity',a.attidentity,'collation',CASE WHEN a.attcollation=0 THEN NULL ELSE a.attcollation::regcollation::text END) ORDER BY a.attnum) FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
   'pk',COALESCE((SELECT jsonb_agg(a.attname ORDER BY k.ord) FROM pg_constraint p CROSS JOIN LATERAL unnest(p.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.num WHERE p.conrelid=c.oid AND p.contype='p'),'[]'::jsonb)) ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','f')),
 'views',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',c.relname,'definition',pg_get_viewdef(c.oid,true),'options',c.reloptions) ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='v'),'[]'::jsonb),
 'other_relations',COALESCE((SELECT jsonb_agg(c.relname ORDER BY c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind NOT IN ('r','p','f','v','S','i')),'[]'::jsonb),
 'constraints',COALESCE((SELECT jsonb_agg(jsonb_build_object('table',c.conrelid::regclass::text,'name',c.conname,'definition',pg_get_constraintdef(c.oid,true),'validated',c.convalidated) ORDER BY c.conrelid::regclass::text,c.conname) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'),'[]'::jsonb),
 'indexes',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',ic.relname,'definition',pg_get_indexdef(i.indexrelid),'valid',i.indisvalid,'ready',i.indisready) ORDER BY ic.relname) FROM pg_index i JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=ic.relnamespace WHERE n.nspname='public'),'[]'::jsonb),
 'sequences',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',c.relname,'type',format_type(s.seqtypid,NULL),'start',s.seqstart,'increment',s.seqincrement,'min',s.seqmin,'max',s.seqmax,'cache',s.seqcache,'cycle',s.seqcycle,'table',t.relname,'column',a.attname) ORDER BY c.relname) FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_depend d ON d.objid=c.oid AND d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i') LEFT JOIN pg_class t ON t.oid=d.refobjid LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid WHERE n.nspname='public'),'[]'::jsonb),
 'extensions',(SELECT jsonb_agg(jsonb_build_object('name',extname,'version',extversion) ORDER BY extname) FROM pg_extension),
 'routines',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',p.proname,'identity',pg_get_function_identity_arguments(p.oid),'definition',pg_get_functiondef(p.oid),'volatility',p.provolatile,'search_path',p.proconfig,'security_definer',p.prosecdef) ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'),'[]'::jsonb),
 'triggers',COALESCE((SELECT jsonb_agg(jsonb_build_object('table',c.relname,'name',t.tgname,'definition',pg_get_triggerdef(t.oid,true),'enabled',t.tgenabled,'constraint',t.tgconstraint<>0) ORDER BY c.relname,t.tgname) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal),'[]'::jsonb),
 'policies',COALESCE((SELECT jsonb_agg(policyname ORDER BY policyname) FROM pg_policies WHERE schemaname='public'),'[]'::jsonb),
 'user_types',COALESCE((SELECT jsonb_agg(t.typname ORDER BY t.typname) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype NOT IN ('c') AND t.typelem=0),'[]'::jsonb))
"""
IDENTITY_SQL = """SELECT jsonb_build_object('database',current_database(),'role',current_user,'address',host(inet_server_addr()),'port',inet_server_port(),'version',current_setting('server_version_num'),'encoding',pg_encoding_to_char(d.encoding),'collate',d.datcollate,'ctype',d.datctype,'provider',d.datlocprovider,'collversion',d.datcollversion,'actual_collversion',pg_database_collation_actual_version(d.oid),'owner',pg_get_userbyid(d.datdba)) FROM pg_database d WHERE d.datname=current_database()"""


class Worker:
    def __init__(self, cfg):
        import psycopg
        from psycopg import sql
        self.pg, self.sql, self.cfg = psycopg, sql, cfg
        self.src = self.dst = None
        self.phase = 'new'
        self.durable = []

    def connect(self, which):
        conn = self.pg.connect(**self.cfg[which], connect_timeout=10)
        conn.execute(SESSION_SETTINGS)
        conn.commit()
        return conn

    def one(self, conn, statement, args=None):
        return conn.execute(statement, args).fetchone()[0]

    def predicate(self, table, alias=None):
        s = self.sql
        prefix = s.Identifier(alias) + s.SQL('.') if alias else s.SQL('')
        scope = classify(table)
        if scope == 'ledger':
            return s.SQL('TRUE'), []
        if scope == 'definition':
            return s.SQL('{}{}=%s AND {}{}=%s').format(prefix, s.Identifier('namespace_id'), prefix, s.Identifier('authority_issuer')), list(DEFINITION)
        return s.SQL('{}{} = ANY(%s)').format(prefix, s.Identifier('deployment_namespace')), [list(NAMESPACES)]

    def query(self, table, include_generated=True):
        s = self.sql
        columns = [s.Identifier(c['name']) for c in table['columns'] if include_generated or not c['generated']]
        predicate, params = self.predicate(table)
        return s.SQL('SELECT {} FROM {} WHERE {} ORDER BY {}').format(s.SQL(',').join(columns), s.Identifier('public', table['name']), predicate, s.SQL(',').join(map(s.Identifier, table['pk']))), params

    def row_hash(self, conn, table):
        s = self.sql
        query, params = self.query(table)
        sha = hashlib.sha256()
        with conn.cursor().copy(s.SQL('COPY ({}) TO STDOUT WITH (FORMAT text)').format(query), params) as stream:
            for block in stream:
                sha.update(block)
        pred, params = self.predicate(table)
        count = self.one(conn, s.SQL('SELECT count(*) FROM {} WHERE {}').format(s.Identifier('public', table['name']), pred), params)
        return {'count': count, 'sha256': sha.hexdigest()}

    def catalog(self, conn):
        result = self.one(conn, CATALOG_SQL)
        validate_catalog(result)
        return result

    def scopes(self, conn, catalog):
        s = self.sql
        result = {}
        seen = set()
        for table in catalog['tables']:
            kind = classify(table)
            if kind == 'ledger':
                continue
            predicate, params = self.predicate(table)
            if kind == 'definition':
                bad = self.one(conn, s.SQL('SELECT count(*) FROM {} WHERE namespace_id=%s AND authority_issuer<>%s').format(s.Identifier('public', table['name'])), list(DEFINITION))
                require(bad == 0, 'ambiguous_erp_definition')
                cols = s.SQL('namespace_id,authority_issuer')
            else:
                cols = s.Identifier('deployment_namespace')
            values = conn.execute(s.SQL('SELECT DISTINCT {} FROM {} WHERE {} ORDER BY {}').format(cols, s.Identifier('public', table['name']), predicate, cols), params).fetchall()
            result[table['name']] = [list(v) for v in values]
            if kind == 'deployment':
                seen.update(v[0] for v in values)
        require('erpnext' in seen and seen <= set(NAMESPACES), 'namespace_inventory')
        return result

    def closure(self, catalog):
        s = self.sql
        rows = self.src.execute("""SELECT c.conrelid::regclass::text,c.confrelid::regclass::text,
          ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(n,o) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n ORDER BY k.o),
          ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(n,o) JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.o)
          FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' AND c.contype='f'""").fetchall()
        tables = {t['name']: t for t in catalog['tables']}
        for child, parent, child_cols, parent_cols in rows:
            require(child in tables and parent in tables, 'external_fk')
            cp, ca = self.predicate(tables[child], 'c')
            pp, pa = self.predicate(tables[parent], 'p')
            join = s.SQL(' AND ').join(s.SQL('c.{}=p.{}').format(s.Identifier(a), s.Identifier(b)) for a,b in zip(child_cols,parent_cols))
            nonnull = s.SQL(' AND ').join(s.SQL('c.{} IS NOT NULL').format(s.Identifier(a)) for a in child_cols)
            query = s.SQL('SELECT EXISTS(SELECT 1 FROM {} c WHERE ({}) AND ({}) AND NOT EXISTS(SELECT 1 FROM {} p WHERE ({}) AND ({})))').format(s.Identifier('public',child),cp,nonnull,s.Identifier('public',parent),join,pp)
            require(not self.one(self.src,query,ca+pa),'selected_fk_not_closed')

    def identity(self, conn):
        info = self.one(conn, IDENTITY_SQL)
        require(info['version'] == '170005' and info['encoding'] == 'UTF8' and info['collate'] == info['ctype'] == 'en_US.utf8' and info['provider'] == 'c' and info['collversion'] == info['actual_collversion'], 'database_version_locale')
        require(info['address'] is not None and info['port'] == 5432, 'connection_address')
        return info

    def open_snapshot(self):
        require(self.phase == 'new','phase_order')
        self.src = self.connect('source')
        self.src.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        self.src.execute(self.sql.SQL('LOCK TABLE {} IN ACCESS SHARE MODE').format(self.sql.SQL(',').join(self.sql.Identifier('public',n) for n in TABLES)))
        info = self.identity(self.src)
        expected = self.cfg['source'] if self.cfg.get('disposable_qa') else {'dbname':SOURCE_DATABASE,'user':SOURCE_ROLE}
        require(info['database'] == expected['dbname'] and info['role'] == expected['user'],'source_identity')
        catalog = self.catalog(self.src)
        self.closure(catalog)
        rows = self.src.execute('SELECT version,name,checksum FROM public.zebra_schema_migrations ORDER BY version').fetchall()
        validate_ledger(rows)
        self.manifest = {'catalog':catalog,'migrations':[list(r) for r in rows], 'source': info, 'scopes':self.scopes(self.src,catalog)}
        self.hashes = {t['name']:self.row_hash(self.src,t) for t in catalog['tables']}
        self.snapshot = self.one(self.src,'SELECT pg_export_snapshot()')
        self.phase = 'snapshot'
        return {'snapshot':self.snapshot,'manifest':self.manifest,'hashes':self.hashes,'fingerprint':digest(self.manifest)}

    def alive(self):
        require(self.src is not None and self.one(self.src,"SELECT current_setting('transaction_read_only')") == 'on', 'snapshot_lost')
        require(self.catalog(self.src) == self.manifest['catalog'],'catalog_drift')

    def quiescence(self):
        # A fresh read-only snapshot detects writes hidden from the exported snapshot.
        conn = self.connect('source')
        try:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            s = self.sql
            tables = {t['name']:t for t in self.manifest['catalog']['tables']}
            for name in ('session_command_pending','broker_command_inbox','broker_control_inbox','broker_outbox','command_shadow_outbox','task_schedules','task_schedule_firings'):
                require(self.row_hash(conn,tables[name])['count']==0,'nonempty_execution_queue')
            predicate,params = self.predicate(tables['worker_leases'])
            require(self.one(conn,s.SQL('SELECT count(*) FROM public.worker_leases WHERE ({}) AND released_at IS NULL').format(predicate),params)==0,'unreleased_worker_lease')
            for name,allowed in (('effect_outbox',['succeeded']),('handoff_dispatch_outbox',['acked'])):
                predicate,params = self.predicate(tables[name])
                require(self.one(conn,s.SQL('SELECT count(*) FROM {} WHERE ({}) AND NOT (status = ANY(%s))').format(s.Identifier('public',name),predicate),params+[allowed])==0,'inflight_dispatch_outbox')
            current = {t['name']:self.row_hash(conn,t) for t in tables.values()}
            require(current==self.hashes,'source_rows_changed_after_snapshot')
        finally:
            conn.rollback()
            conn.close()

    def target(self, approved):
        require(self.phase == 'snapshot','phase_order')
        require(self.manifest == approved['manifest'] and self.hashes == approved['hashes'],'approval_drift')
        self.alive()
        self.quiescence()
        cfg = self.cfg
        self.dst = self.connect('destination')
        info = self.identity(self.dst)
        require(info['database'] == cfg['destination']['dbname'] and info['role'] == info['owner'] == cfg['destination']['user'] and info['database'] != self.manifest['source']['database'] and info['role'] != self.manifest['source']['role'], 'destination_identity')
        require(info['address'] == cfg['target_address'] and info['address'] != self.manifest['source']['address'] and self.manifest['source']['address'] == cfg['source_address'],'distinct_server')
        attrs = self.dst.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname=current_user').fetchone()
        require(attrs == (False,False,False,False,False,True),'destination_privilege')
        require(self.one(self.dst,'SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)') == 0,'destination_membership')
        require(self.one(self.src,'SELECT count(*) FROM pg_roles WHERE rolname=%s',[info['role']]) == 0,'role_present_on_source')
        # Attempt with exact destination credentials at the actual original endpoint.
        probe = dict(cfg['destination'])
        for key in ('host','hostaddr','port','dbname'):
            probe.pop(key,None)
            if key in cfg['source']:
                probe[key] = cfg['source'][key]
        try:
            conn = self.pg.connect(**probe,connect_timeout=5)
        except self.pg.OperationalError as error:
            require(error.sqlstate in ('28P01','28000') or 'password authentication failed' in str(error) or 'role' in str(error) and 'does not exist' in str(error),'source_authentication_not_proven')
        else:
            conn.close()
            raise Refusal('destination_credentials_work_on_source')
        objects = self.one(self.dst,"""SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%') + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema')) + (SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('public','pg_catalog','information_schema') AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp%') + (SELECT count(*) FROM pg_extension WHERE extname<>'plpgsql') + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype<>'c' AND t.typelem=0)""")
        require(objects == 0,'destination_nonempty')
        self.dst.commit()
        self.phase = 'target_checked'
        return {'target_checked':True}

    def pre_restored(self):
        require(self.phase == 'target_checked','phase_order')
        self.alive()
        self.durable.append('pre_data')
        self.phase = 'pre_restored'
        return {'phase':self.phase}

    def copy_table(self, table):
        s = self.sql
        query,params = self.query(table,False)
        cols = s.SQL(',').join(s.Identifier(c['name']) for c in table['columns'] if not c['generated'])
        with self.src.cursor().copy(s.SQL('COPY ({}) TO STDOUT WITH (FORMAT text)').format(query),params) as source:
            with self.dst.cursor().copy(s.SQL('COPY {} ({}) FROM STDIN WITH (FORMAT text)').format(s.Identifier('public',table['name']),cols)) as target:
                for block in source:
                    target.write(block)

    def copy_rows(self):
        require(self.phase == 'pre_restored','phase_order')
        self.alive()
        try:
            for table in self.manifest['catalog']['tables']:
                self.copy_table(table)
            self.dst.commit()
        except BaseException:
            self.dst.rollback()
            raise
        self.durable.append('data')
        self.phase = 'copied'
        return {'phase':self.phase,'tables':len(TABLES)}

    def verify(self):
        require(self.phase == 'copied','phase_order')
        self.alive()
        self.durable.append('post_data')
        require(self.catalog(self.dst) == self.manifest['catalog'],'restored_catalog_mismatch')
        s = self.sql
        sequences = []
        for seq in self.manifest['catalog']['sequences']:
            maximum = self.one(self.dst,s.SQL('SELECT max({}) FROM {}').format(s.Identifier(seq['column']),s.Identifier('public',seq['table'])))
            value,called = next_sequence(seq,maximum)
            self.one(self.dst,'SELECT setval(%s::regclass,%s,%s)',['public.'+s.Identifier(seq['name']).as_string(self.dst),value,called])
            actual = self.dst.execute(s.SQL('SELECT last_value,is_called FROM {}').format(s.Identifier('public',seq['name']))).fetchone()
            require(actual == (value,called),'sequence_state')
            require(maximum is None or actual[0]+1>maximum,'sequence_collision')
            sequences.append({'name':seq['name'],'last_value':value,'is_called':called})
        self.dst.commit()
        self.durable.append('sequences')
        for table in self.manifest['catalog']['tables']:
            pred, params = self.predicate(table)
            require(self.one(self.dst,s.SQL('SELECT count(*) FROM {} WHERE NOT ({})').format(s.Identifier('public',table['name']),pred),params)==0,'foreign_destination_scope')
        require(self.scopes(self.dst,self.manifest['catalog']) == self.manifest['scopes'],'scope_mismatch')
        result = {t['name']:self.row_hash(self.dst,t) for t in self.manifest['catalog']['tables']}
        require(result == self.hashes,'row_count_or_hash_mismatch')
        # Source snapshot remains alive through both native restores and target verification.
        self.alive()
        self.quiescence()
        self.dst.rollback()
        self.phase = 'verified'
        return {'status':'verified_unactivated','fingerprint':digest(self.manifest),'hashes':result,'sequences':sequences,'durable_phases':self.durable,'consumers_released':False}

    def abort(self):
        failed = False
        for conn in (self.dst,self.src):
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    failed = True
                finally:
                    conn.close()
        self.dst = self.src = None
        require(not failed,'abort_connection_failure')
        return {'status':'closed','durable_phases':self.durable,'consumers_released':False}


def worker_main(path):
    worker = Worker(json.loads(secure_read(path)))
    allowed = {'open_snapshot','target','pre_restored','copy_rows','verify','abort'}
    try:
        for line in sys.stdin:
            require(len(line) < 16_000_000,'protocol_bound')
            request = json.loads(line)
            command = request['command']
            require(command in allowed,'protocol_command')
            try:
                result = getattr(worker,command)(**request.get('arguments',{}))
                print(json.dumps({'ok':True,'result':result}),flush=True)
                if command == 'abort':
                    return
            except BaseException as error:
                print(json.dumps({'ok':False,'phase':worker.phase,'sqlstate':getattr(error,'sqlstate',None),'reason':str(error) if isinstance(error,Refusal) else 'worker_failure','durable_phases':worker.durable,'consumers_released':False}),flush=True)
                return
    finally:
        worker.abort()


def validate_gate(evidence):
    from datetime import datetime, timezone
    require(evidence.get('version') == 1 and evidence.get('reviewed_by_operator') and evidence.get('site') == 'erpnext.zebra.local','operator_gate_identity')
    observed = datetime.fromisoformat(evidence['observed_at'].replace('Z','+00:00'))
    require(0 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 1800,'operator_gate_expired')
    require(len(evidence.get('guard_source_commit','')) == 40,'operator_gate_commit')
    require(evidence.get('admission_probe',{}).get('http_status') in (409,417,423,503) and evidence['admission_probe'].get('cloud_mutations') == 0 and evidence['admission_probe'].get('evidence_ref') and len(evidence['admission_probe'].get('response_sha256',''))==64,'operator_gate_probe')
    drain = evidence.get('conversation_lock_drain',{})
    require(drain.get('outstanding') == 0 and isinstance(drain.get('checked'),int) and drain['checked'] >= 0 and drain.get('evidence_ref'),'operator_gate_drain')
    require(evidence.get('unresolved') == [] and evidence.get('producer_inventory'),'operator_gate_unresolved')
    for producer in evidence['producer_inventory']:
        require(set(('identity','kind','state','evidence_ref')) <= set(producer) and producer['state'] in ('stopped','disabled') and producer['identity'] and producer['evidence_ref'],'operator_gate_producer')
    return {'sha256':hashlib.sha256(canonical(evidence)).hexdigest(),'observed_at':evidence['observed_at'],'assurance':'operator-reviewed attestation; external Host probe/locks/process coverage not independently verified by transfer tool'}


class Host:
    def __init__(self, path, disposable_qa=False):
        self.disposable_qa = disposable_qa
        os.umask(0o077)
        self.cfg = json.loads(secure_read(path))
        cfg = self.cfg
        keys = {'source','destination','destination_container','destination_network','destination_volume','evidence_directory'}
        keys |= {'qa_source_container','qa_source_network'} if disposable_qa else {'gate_evidence','gate_sha256'}
        require(set(cfg) == keys,'configuration_keys')
        for name in ('source','destination'):
            require(set(cfg[name]) <= {'host','port','dbname','user','password','sslmode'} and {'host','dbname','user','password'} <= set(cfg[name]),'connection_keys')
            require(all(isinstance(v,(str,int)) for v in cfg[name].values()),'connection_values')
            require(cfg[name].get('port',5432) == 5432,'connection_port')
            require(all(isinstance(cfg[name][k],str) and cfg[name][k] and '\x00' not in cfg[name][k] for k in ('host','dbname','user','password')),'connection_values')
        self.source_container = cfg.get('qa_source_container',SOURCE_CONTAINER)
        self.source_network = cfg.get('qa_source_network',SOURCE_NETWORK)
        self.source_database,self.source_role = cfg['source']['dbname'],cfg['source']['user']
        if disposable_qa:
            require(self.source_container.startswith('erpnext-db-qa-source-') and cfg['destination_container'].startswith('erpnext-db-qa-target-') and self.source_network==cfg['destination_network'] and self.source_network.startswith('erpnext-db-transfer-qa-') and self.source_database.startswith('zebra_transfer_qa_source_') and cfg['destination']['dbname'].startswith('erpnext_agent_qa_'),'disposable_qa_identity')
        else:
            require(self.source_database == SOURCE_DATABASE and self.source_role == SOURCE_ROLE,'source_configuration')
            require(cfg['destination_network'] != SOURCE_NETWORK,'distinct_configuration')
        require(cfg['destination_container'] != self.source_container,'distinct_configuration')
        self.directory = Path(cfg['evidence_directory']).absolute()
        require(self.directory.is_dir() and not self.directory.is_symlink() and stat.S_IMODE(self.directory.stat().st_mode)==0o700 and self.directory.stat().st_uid==os.geteuid(),'evidence_directory')
        # Every invocation gets an immutable subdirectory; never reuse an incomplete target.
        self.run_directory = self.directory / ('transfer-'+uuid.uuid4().hex)
        self.run_directory.mkdir(mode=0o700)
        self.log = open(self.run_directory/'diagnostics.log','xb')
        os.chmod(self.log.name,0o600)
        self.process = None
        self.container = None
        self.phase = 'host_preflight'

    def run(self,args,stdout=subprocess.PIPE,stdin=None):
        try:
            result = subprocess.run(args,stdin=stdin,stdout=stdout,stderr=self.log,check=True)
            return result.stdout
        except subprocess.CalledProcessError:
            raise Refusal('native_command_failed') from None

    def inspect_container(self,name):
        return json.loads(self.run(['docker','inspect',name]))[0]

    def gates(self):
        if self.disposable_qa:
            network = json.loads(self.run(['docker','network','inspect',self.source_network]))[0]
            allowed = {self.source['Id'],self.target['Id']} | ({self.container} if self.container else set())
            require(network['Internal'] and set(network.get('Containers',{})) <= allowed,'qa_network_consumer')
            return {'assurance':'disposable QA only; isolated internal network contains only two verified database servers and maintenance process'}
        for name in CONSUMERS:
            state = self.inspect_container(name)['State']
            require(state['Status'] in ('exited','created') and not state['Running'] and not state.get('Restarting'),'source_consumer_running')
        raw = secure_read(self.cfg['gate_evidence'])
        require(hashlib.sha256(raw).hexdigest() == self.cfg['gate_sha256'],'operator_gate_fingerprint')
        gate = validate_gate(json.loads(raw))
        network = json.loads(self.run(['docker','network','inspect',self.cfg['destination_network']]))[0]
        allowed = {self.target['Id']}
        if self.container:
            allowed.add(self.container)
        require(set(network.get('Containers',{})) <= allowed,'destination_network_consumer')
        gate['raw_file_sha256'] = self.cfg['gate_sha256']
        return gate

    def preflight(self,transfer=False):
        cfg = self.cfg
        self.source = self.inspect_container(self.source_container)
        self.target = self.inspect_container(cfg['destination_container'])
        require(self.source['Id'] != self.target['Id'],'same_container')
        for container in (self.source,self.target):
            require(container['Image'] == PG_IMAGE and container['State']['Running'],'postgres_image_or_state')
        require(set(self.source['NetworkSettings']['Networks']) == {self.source_network},'source_network_drift')
        require(set(self.target['NetworkSettings']['Networks']) == {cfg['destination_network']},'target_network')
        require(not self.target['HostConfig'].get('PortBindings') and not any(self.target['NetworkSettings']['Ports'].values()),'published_destination_port')
        require(self.target['HostConfig'].get('NetworkMode') != 'host','target_host_network')
        if self.disposable_qa:
            require(all(c['Config'].get('Labels',{}).get('zebra.erp.qa')=='database-transfer' for c in (self.source,self.target)),'qa_container_label')
        source_mounts = {m['Source'] for m in self.source['Mounts']}
        mounts = [m for m in self.target['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
        require(len(mounts)==1 and mounts[0]['Type']=='volume' and mounts[0]['Name']==cfg['destination_volume'] and mounts[0]['Source'] not in source_mounts,'distinct_target_volume')
        self.source_address = self.source['NetworkSettings']['Networks'][self.source_network]['IPAddress']
        self.target_address = self.target['NetworkSettings']['Networks'][cfg['destination_network']]['IPAddress']
        require(cfg['source']['host']==self.source_address and cfg['destination']['host']==self.target_address and self.source_address!=self.target_address,'connection_container_address')
        require(self.run(['docker','image','inspect','--format','{{.Id}}',API_IMAGE]).decode().strip()==API_IMAGE,'worker_image')
        self.host_identity = {'docker_engine':self.run(['docker','info','--format','{{.ID}}']).decode().strip(),
            'source_container':self.source['Id'],'destination_container':self.target['Id'],
            'source_image':self.source['Image'],'destination_image':self.target['Image'],
            'source_mounts':self.source['Mounts'],'destination_mounts':self.target['Mounts'],
            'source_network':json.loads(self.run(['docker','network','inspect',self.source_network]))[0]['Id'],
            'destination_network':json.loads(self.run(['docker','network','inspect',cfg['destination_network']]))[0]['Id']}
        require(self.host_identity['docker_engine'],'docker_engine_identity')
        if transfer:
            return self.gates()
        return None

    def start_worker(self):
        config = {'source':self.cfg['source'],'destination':self.cfg['destination'],'source_address':self.source_address,'target_address':self.target_address,'disposable_qa':self.disposable_qa}
        secure_write(self.run_directory/'worker.json',canonical(config))
        secure_write(self.run_directory/'worker.py',Path(__file__).read_bytes())
        self.container = self.run(['docker','create','--interactive','--network',self.source_network,'--user',f'{os.geteuid()}:{os.getegid()}','--read-only','--cap-drop=ALL','--security-opt','no-new-privileges','--mount',f'type=bind,src={self.run_directory},dst=/transfer,readonly','--entrypoint','/app/.venv/bin/python',API_IMAGE,'/transfer/worker.py','worker','/transfer/worker.json']).decode().strip()
        require(len(self.container)==64 and all(c in '0123456789abcdef' for c in self.container),'maintenance_container_id')
        if self.cfg['destination_network'] != self.source_network:
            self.run(['docker','network','connect',self.cfg['destination_network'],self.container])
        self.process = subprocess.Popen(['docker','start','--attach','--interactive',self.container],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)

    def command(self,command,**arguments):
        self.phase = command
        self.process.stdin.write(json.dumps({'command':command,'arguments':arguments})+'\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline(32_000_000)
        require(line and line.endswith('\n'),'worker_protocol_lost')
        response = json.loads(line)
        if not response.get('ok'):
            # Only the fixed-code worker response may reach the user, never native stderr.
            raise Refusal('worker_'+response.get('reason','failure')+'_sqlstate_'+str(response.get('sqlstate')))
        return response['result']

    def dump(self,section,snapshot):
        require(isinstance(snapshot,str) and len(snapshot)<100 and all(c in '0123456789ABCDEFabcdef-' for c in snapshot),'snapshot_identifier')
        path = self.run_directory/(section+'.sql')
        with open(path,'xb') as out:
            self.run(['docker','exec','-u','postgres',self.source['Id'],'pg_dump','-U',self.source_role,'-d',self.source_database,'--schema-only','--schema=public','--no-owner','--no-acl','--section='+section,'--snapshot='+snapshot,'--lock-wait-timeout=10s'],stdout=out)
        os.chmod(path,0o600)
        return path

    def restore(self,path,pre=False):
        destination = self.cfg['destination']
        # Local Unix socket authentication must already be operator-configured. No password in argv/env.
        if pre:
            restore = self.run_directory/'pre-restore.sql'
            with open(restore,'xb') as out,open(path,'rb') as source:
                out.write(b'DROP SCHEMA public RESTRICT;\n')
                while block := source.read(1024*1024):
                    out.write(block)
            os.chmod(restore,0o600)
        else:
            restore = path
        with open(restore,'rb') as source,open(self.run_directory/('pre-psql.log' if pre else 'post-psql.log'),'xb') as output:
            self.run(['docker','exec','-i','-u','postgres',self.target['Id'],'psql','-X','-w','-U',destination['user'],'-d',destination['dbname'],'-v','ON_ERROR_STOP=1','--single-transaction'],stdin=source,stdout=output)

    def execute(self,mode,approved_path=None,fingerprint=None):
        failed = False
        try:
            gate = self.preflight(mode=='transfer')
            if mode=='transfer':
                raw = secure_read(approved_path)
                approved = json.loads(raw)
                require(hashlib.sha256(raw).hexdigest()==fingerprint,'approved_file_fingerprint')
                require(approved.get('host_identity')==self.host_identity,'approved_host_identity_drift')
            self.start_worker()
            snapshot = self.command('open_snapshot')
            snapshot['host_identity'] = self.host_identity
            secure_write(self.run_directory/'inspection.json',canonical(snapshot))
            if mode=='inspect':
                self.command('abort')
                return {'status':'inspection_only','fingerprint':hashlib.sha256(canonical(snapshot)).hexdigest(),'inspection_file':str(self.run_directory/'inspection.json'),'tables':len(TABLES),'destination_mutations':False,'gate_required_before_transfer':True}
            self.command('target',approved=approved)
            self.phase = 'dump_schema'
            pre = self.dump('pre-data',snapshot['snapshot'])
            post = self.dump('post-data',snapshot['snapshot'])
            self.gates()
            self.phase = 'restore_pre_data'
            self.restore(pre,True)
            self.command('pre_restored')
            self.command('copy_rows')
            self.phase = 'restore_post_data'
            self.restore(post)
            report = self.command('verify')
            self.gates()
            report['operator_gate'] = gate
            report['host_identity'] = self.host_identity
            secure_write(self.run_directory/'verified.json',canonical(report))
            self.command('abort')
            return {'status':report['status'],'report_file':str(self.run_directory/'verified.json'),'fingerprint':report['fingerprint'],'consumers_released':False}
        except BaseException:
            failed = True
            self.record_incomplete()
            raise
        finally:
            try:
                self.close()
            except BaseException:
                self.record_incomplete()
                if not failed:
                    raise

    def record_incomplete(self):
        try:
            secure_write(self.run_directory/'INCOMPLETE.json',canonical({'phase':self.phase,'status':'incomplete_unactivated','warning':'pre-data, data, post-data and sequence changes may already be durable; do not retry into this target or release consumers'}))
        except OSError:
            pass  # Preserve the primary failure even if evidence storage itself fails.

    def close(self):
        self.cleanup_report = {'maintenance_container_absent':self.container is None,'credential_copy_removed':False,'errors':[]}
        try:
            if self.process and self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=10)
                except (OSError,subprocess.TimeoutExpired):
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
        except BaseException:
            self.cleanup_report['errors'].append('attach_process_termination_failed')
        try:
            if self.container:
                self.run(['docker','rm','--force',self.container])
                self.cleanup_report['maintenance_container_absent'] = True
        except BaseException:
            self.cleanup_report['errors'].append('maintenance_container_removal_not_proven')
        finally:
            try:
                (self.run_directory/'worker.json').unlink(missing_ok=True)
                self.cleanup_report['credential_copy_removed'] = True
            except OSError:
                self.cleanup_report['errors'].append('credential_copy_removal_failed')
            self.log.close()
        if self.cleanup_report['errors']:
            try:
                secure_write(self.run_directory/'CLEANUP_INCOMPLETE.json',canonical(self.cleanup_report))
            except OSError:
                pass
            raise Refusal('maintenance_cleanup_incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('inspect','transfer','worker'))
    parser.add_argument('config')
    parser.add_argument('--disposable-qa',action='store_true',help='strict labeled isolated QA endpoints only; never production')
    parser.add_argument('--approved')
    parser.add_argument('--fingerprint')
    args = parser.parse_args()
    if args.mode=='worker':
        worker_main(args.config)
        return
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(Refusal('terminated')))
    host = None
    try:
        require(args.mode!='transfer' or args.approved and args.fingerprint,'approval_required')
        host = Host(args.config,args.disposable_qa)
        report = host.execute(args.mode,args.approved,args.fingerprint)
    except BaseException as error:
        print(json.dumps({'status':'failed_unactivated','phase':getattr(host,'phase','configuration'),'cleanup':getattr(host,'cleanup_report',{}),'reason':str(error) if isinstance(error,Refusal) else 'operator_failure','sqlstate':getattr(error,'sqlstate',None),'consumers_released':False}),flush=True)
        sys.exit(1)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    main()
