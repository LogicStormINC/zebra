"""Pinned native105 schema inventory and owner-independent catalog queries."""

NAMESPACES = ("erpnext", "erpnext-history", "erpnext-continuation")
DEFINITION = ("erpnext", "https://erpnext.zebra.local")
PG_IMAGE = "sha256:5d004e058f520673f1f6edbad6b1603d5dab4c818e257c041889ef64672a8cc4"
API_IMAGE = "sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef"
SOURCE_CONTAINER = "zebra-dependencies-postgres-1"
SOURCE_DATABASE = SOURCE_ROLE = "zebra"
SOURCE_NETWORK = "zebra-dependencies"
CONSUMERS = ("erpnext-agent-api-1", "erpnext-agent-worker-1")
TABLES = """active_context_projections
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
zebra_schema_migrations""".split()
ROUTINES = """advance_coverage_lineage_versions
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
write_projection_source_metadata""".split()
TRIGGERS = [
    tuple(pair.split(":"))
    for pair in """agent_tasks:agent_tasks_projection_work_insert
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
task_event_index:task_event_reservation_guard""".split()
]
DEFINITIONS = set(
    (
        "agent_definition_draft_validations agent_definition_drafts agent"
        "_definition_eval_evidence agent_definition_records agent_definit"
        "ion_versions agent_release_records"
    ).split()
)
SEQUENCE_OWNERS = {
    ("command_delivery_scope_rollout_audit", "change_id"),
    ("control_plane_delivery_audit_records", "audit_id"),
    ("host_grant_audit", "audit_id"),
    ("mcp_catalog_versions", "publication_sequence"),
}
SESSION_SETTINGS = (
    "SET client_encoding='UTF8'; SET timezone='UTC'; SET datestyle='I"
    "SO, YMD'; SET extra_float_digits=3; SET bytea_output='hex'; SET "
    "intervalstyle='postgres'; SET search_path=public,pg_catalog; SET"
    " statement_timeout='15min'; SET lock_timeout='10s'"
)


# Catalog definitions are owner/OID independent, so native restore can be compared exactly.
CATALOG_SQL = (
    "\nSELECT jsonb_build_object(\n 'tables', (SELECT jsonb_agg(jsonb_b"
    "uild_object('name',c.relname,'kind',c.relkind,'partition',c.reli"
    "spartition,'persistence',c.relpersistence,'replica_identity',c.r"
    "elreplident,'options',c.reloptions,'rls',c.relrowsecurity,'force"
    "_rls',c.relforcerowsecurity,\n   'columns',(SELECT jsonb_agg(json"
    "b_build_object('name',a.attname,'number',a.attnum,'type',format_"
    "type(a.atttypid,a.atttypmod),'notnull',a.attnotnull,'default',pg"
    "_get_expr(d.adbin,d.adrelid),'generated',a.attgenerated,'identit"
    "y',a.attidentity,'collation',CASE WHEN a.attcollation=0 THEN NUL"
    "L ELSE a.attcollation::regcollation::text END) ORDER BY a.attnum"
    ") FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attr"
    "elid AND d.adnum=a.attnum WHERE a.attrelid=c.oid AND a.attnum>0 "
    "AND NOT a.attisdropped),\n   'pk',COALESCE((SELECT jsonb_agg(a.at"
    "tname ORDER BY k.ord) FROM pg_constraint p CROSS JOIN LATERAL un"
    "nest(p.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON"
    " a.attrelid=c.oid AND a.attnum=k.num WHERE p.conrelid=c.oid AND "
    "p.contype='p'),'[]'::jsonb)) ORDER BY c.relname) FROM pg_class c"
    " JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='pu"
    "blic' AND c.relkind IN ('r','p','f')),\n 'views',COALESCE((SELECT"
    " jsonb_agg(jsonb_build_object('name',c.relname,'definition',pg_g"
    "et_viewdef(c.oid,true),'options',c.reloptions) ORDER BY c.relnam"
    "e) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace W"
    "HERE n.nspname='public' AND c.relkind='v'),'[]'::jsonb),\n 'other"
    "_relations',COALESCE((SELECT jsonb_agg(c.relname ORDER BY c.reln"
    "ame) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace"
    " WHERE n.nspname='public' AND c.relkind NOT IN ('r','p','f','v',"
    "'S','i')),'[]'::jsonb),\n 'constraints',COALESCE((SELECT jsonb_ag"
    "g(jsonb_build_object('table',c.conrelid::regclass::text,'name',c"
    ".conname,'definition',pg_get_constraintdef(c.oid,true),'validate"
    "d',c.convalidated) ORDER BY c.conrelid::regclass::text,c.conname"
    ") FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespa"
    "ce WHERE n.nspname='public'),'[]'::jsonb),\n 'indexes',COALESCE(("
    "SELECT jsonb_agg(jsonb_build_object('name',ic.relname,'definitio"
    "n',pg_get_indexdef(i.indexrelid),'valid',i.indisvalid,'ready',i."
    "indisready) ORDER BY ic.relname) FROM pg_index i JOIN pg_class i"
    "c ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=ic.relname"
    "space WHERE n.nspname='public'),'[]'::jsonb),\n 'sequences',COALE"
    "SCE((SELECT jsonb_agg(jsonb_build_object('name',c.relname,'type'"
    ",format_type(s.seqtypid,NULL),'start',s.seqstart,'increment',s.s"
    "eqincrement,'min',s.seqmin,'max',s.seqmax,'cache',s.seqcache,'cy"
    "cle',s.seqcycle,'table',t.relname,'column',a.attname) ORDER BY c"
    ".relname) FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid"
    " JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_depend"
    " d ON d.objid=c.oid AND d.classid='pg_class'::regclass AND d.ref"
    "classid='pg_class'::regclass AND d.deptype IN ('a','i') LEFT JOI"
    "N pg_class t ON t.oid=d.refobjid LEFT JOIN pg_attribute a ON a.a"
    "ttrelid=t.oid AND a.attnum=d.refobjsubid WHERE n.nspname='public"
    "'),'[]'::jsonb),\n 'extensions',(SELECT jsonb_agg(jsonb_build_obj"
    "ect('name',extname,'version',extversion) ORDER BY extname) FROM "
    "pg_extension),\n 'routines',COALESCE((SELECT jsonb_agg(jsonb_buil"
    "d_object('name',p.proname,'identity',pg_get_function_identity_ar"
    "guments(p.oid),'definition',pg_get_functiondef(p.oid),'volatilit"
    "y',p.provolatile,'search_path',p.proconfig,'security_definer',p."
    "prosecdef) ORDER BY p.proname,pg_get_function_identity_arguments"
    "(p.oid)) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamesp"
    "ace WHERE n.nspname='public'),'[]'::jsonb),\n 'triggers',COALESCE"
    "((SELECT jsonb_agg(jsonb_build_object('table',c.relname,'name',t"
    ".tgname,'definition',pg_get_triggerdef(t.oid,true),'enabled',t.t"
    "genabled,'constraint',t.tgconstraint<>0) ORDER BY c.relname,t.tg"
    "name) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN "
    "pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
    "AND NOT t.tgisinternal),'[]'::jsonb),\n 'policies',COALESCE((SELE"
    "CT jsonb_agg(policyname ORDER BY policyname) FROM pg_policies WH"
    "ERE schemaname='public'),'[]'::jsonb),\n 'user_types',COALESCE((S"
    "ELECT jsonb_agg(t.typname ORDER BY t.typname) FROM pg_type t JOI"
    "N pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public"
    "' AND t.typtype NOT IN ('c') AND t.typelem=0),'[]'::jsonb))\n"
)
IDENTITY_SQL = (
    "SELECT jsonb_build_object('database',current_database(),'role',c"
    "urrent_user,'address',host(inet_server_addr()),'port',inet_serve"
    "r_port(),'version',current_setting('server_version_num'),'encodi"
    "ng',pg_encoding_to_char(d.encoding),'collate',d.datcollate,'ctyp"
    "e',d.datctype,'provider',d.datlocprovider,'collversion',d.datcol"
    "lversion,'actual_collversion',pg_database_collation_actual_versi"
    "on(d.oid),'owner',pg_get_userbyid(d.datdba)) FROM pg_database d "
    "WHERE d.datname=current_database()"
)
