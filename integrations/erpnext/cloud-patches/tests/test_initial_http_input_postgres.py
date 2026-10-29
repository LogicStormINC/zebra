"""Explicit disposable-DB check. Never point this at an ERP/Trench database.

Set ZEBRA_HTTP_INPUT_QA_DSN to an EMPTY database named zebra_http_input_qa_*
created for this check; uses the installed native dependencies and overlay imports.
"""
import os
import overlay_imports
import psycopg
from dataclasses import replace
from datetime import UTC,datetime
from hashlib import sha256
from uuid import uuid4

# Reuse the checked real Core/bootstrap/objects data, not a second fake schema.
import test_initial_http_input as fixture
from agent_storage.postgres.host_auth import HostRegistryRecord,HostGrantAttempt,PostgresHostAuthorityStore
from agent_storage.postgres.migration_runner import apply_postgres_migrations,require_current_schema
from agent_storage import bootstrap_control_plane_epoch
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_core.domain.http_input_attachments import HttpInputAuthority
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_core.application import SessionBootstrapCommand,SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType
from agent_storage.postgres.http_input_attachments import prepare_http_input

raw=os.environ.get('ZEBRA_HTTP_INPUT_QA_DSN')
if not raw:
    raise SystemExit('Set ZEBRA_HTTP_INPUT_QA_DSN for an empty zebra_http_input_qa_* database')
with psycopg.connect(raw) as c:
    assert c.execute('SELECT current_database()').fetchone()[0].startswith('zebra_http_input_qa_'), 'Refusing non-QA database'
    assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]==0, 'QA database must be empty'
apply_postgres_migrations(raw);require_current_schema(raw)
namespace='erpnext'
bootstrap_control_plane_epoch(raw,deployment_namespace=namespace)
store=PostgresHostAuthorityStore(raw,deployment_namespace=namespace)
record=HostRegistryRecord(**fixture.registry)
store.upsert_registry(record)
digest=lambda values:sha256('\x1f'.join(sorted(values)).encode()).hexdigest()
attempt=HostGrantAttempt(issuer=record.issuer,jti=fixture.context.grant_id,host_app_id=record.host_app_id,
    namespace_id=record.namespace_id,algorithm='RS256',grant_digest=fixture.proof.grant_digest,
    scopes_digest=digest(fixture.context.scopes),resource_digest=digest(f'{r.resource_type}:{r.resource_id}' for r in fixture.context.resource_refs),
    expires_at=fixture.context.expires_at)
decision=store.consume_grant(attempt,expected_registry=record);assert decision.accepted
proof=fixture.proof.model_copy(update={'audit_id':decision.audit.audit_id})
authority=fixture.authority.model_copy(update={'proof':proof})
objects=fixture.Objects();event,batch=prepare_http_input(objects,namespace,authority,fixture.raw_event,fixture.inputs)
events=tuple(event if e.event_id==event.event_id else e for e in fixture.bootstrap.events)
receipt=IdempotencyRecord(action='session.create',idempotency_key='qa-original',request_hash='a'*64,
    status_code=201,response_body={'session_id':str(event.session_id),'attachments':[entry.reference.to_mapping() for entry in batch.entries]},
    created_at=datetime.now(UTC))
request=TaskAdmissionRequest(events=events,session=fixture.bootstrap.session,
    workspace=rebuild_workspace(list(events)),binding=fixture.bound,idempotency=receipt,http_input=batch)
transaction=PostgresTaskAdmissionTransaction(raw,deployment_namespace=namespace)
accepted=transaction.admit(request);assert not accepted.idempotent_replay
replayed=transaction.admit(request);assert replayed.idempotent_replay
metadata=PostgresCloudArtifactPayloadStore(raw,deployment_namespace=namespace)
for entry in batch.entries:
    value=metadata.get_metadata(ArtifactMetadataQuery(deployment_namespace=namespace,
        session_id=event.session_id,artifact_id=entry.reference.attachment_id))
    assert value.authority_kind=='http_input' and value.input_authority.proof==proof
    assert value.object_receipt==entry.receipt
with psycopg.connect(raw) as c:
    assert c.execute('SELECT count(*) FROM artifact_payload_metadata').fetchone()[0]==4
    assert c.execute('SELECT max(version) FROM zebra_schema_migrations').fetchone()[0]==106
    try:
        with c.transaction():
            c.execute("UPDATE artifact_payload_metadata SET http_input_authority=NULL")
        raise AssertionError('NULL HTTP proof passed CHECK')
    except psycopg.errors.CheckViolation:pass
    c.execute("UPDATE artifact_payload_metadata SET lifecycle_status='pruning',pruning_at=clock_timestamp()")
    c.execute("UPDATE artifact_payload_metadata SET lifecycle_status='pruned',pruned_at=clock_timestamp()")
# A failure after bootstrap+binding inserts must roll every canonical fact back.
boot=SessionBootstrapService().build(SessionBootstrapCommand(title='rollback',user_input='never accepted',
    workspace_root='/tmp/http-input-rollback',host_context=fixture.context))
user=next(e for e in boot.events if e.event_type is EventType.USER_MESSAGE_RECEIVED)
bound=fixture.binding(user.session_id)
bad=HttpInputAuthority(context=fixture.context,proof=proof,task_id=str(user.session_id),binding_digest='0'*64)
attached,batch2=prepare_http_input(objects,namespace,bad,user,fixture.inputs[:1])
events2=tuple(attached if e.event_id==user.event_id else e for e in boot.events)
try:
    transaction.admit(TaskAdmissionRequest(events=events2,session=boot.session,
        workspace=rebuild_workspace(list(events2)),binding=bound,http_input=batch2,
        idempotency=replace(receipt,idempotency_key='qa-rollback')))
    raise AssertionError('Bad authority was admitted')
except ValueError:pass
with psycopg.connect(raw) as c:
    assert c.execute('SELECT count(*) FROM session_events WHERE session_id=%s',(user.session_id,)).fetchone()[0]==0
    assert c.execute('SELECT count(*) FROM artifact_payload_metadata WHERE session_id=%s',(user.session_id,)).fetchone()[0]==0
    assert c.execute("SELECT count(*) FROM control_plane_idempotency_records WHERE idempotency_key='qa-rollback'").fetchone()[0]==0
print('PASS real disposable PostgreSQL: schema106/four inputs/read model/idempotent replay/retention states/atomic rollback')
