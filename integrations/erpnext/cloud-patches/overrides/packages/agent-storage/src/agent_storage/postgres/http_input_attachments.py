"""Immutable object staging and transaction-only verified HTTP input admission."""
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from psycopg.types.json import Jsonb
from agent_core.application import attachment_refs_from_event
from agent_core.application.session_attachments import attach_refs_to_user_event
from agent_core.domain.artifact_objects import ArtifactObjectExpectation, ArtifactObjectPutRequest
from agent_core.domain.attachments import SessionAttachmentRef
from agent_core.domain.cloud_artifact_requests import ArtifactReserveRequest, canonical_artifact_reserve_hash
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.http_input_attachments import (
    HttpInputAuthority, PreparedHttpInputAttachment, PreparedHttpInputBatch, registry_policy_digest,
)
from agent_core.domain.image_attachments import ImageAttachmentInput
from agent_core.domain.task_bindings import require_task_host_context


class HttpInputAuthorityError(ValueError):
    """A staged input lost its current native Host authorization."""


def check_input_authority(connection, namespace, authority, binding):
    context, proof = authority.context, authority.proof
    try:
        context.require_scope('agent.run')
    except ValueError as error:
        raise HttpInputAuthorityError('HTTP input agent.run scope is required') from error
    if (proof.deployment_namespace != namespace or proof.grant_id != context.grant_id
        or proof.expires_at != context.expires_at or binding.binding_digest != authority.binding_digest
        or str(binding.task_id) != authority.task_id):
        raise HttpInputAuthorityError('HTTP input authority binding conflicts')
    registry = connection.execute(
        '''SELECT host_app_id,namespace_id,issuer,audience,jwks_uri,allowed_origins,
                  algorithms,policy_version,active FROM host_authority_registries
           WHERE deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s FOR SHARE''',
        (namespace, context.host_app_id, context.namespace_id),
    ).fetchone()
    if (registry is None or registry['active'] is not True
        or registry_policy_digest(registry) != proof.trust_policy_revision
        or registry['policy_version'] != proof.policy_version
        or context.policy_version != proof.policy_version):
        raise HttpInputAuthorityError('HTTP input trust policy changed')
    evidence = connection.execute(
        '''SELECT ledger.expires_at,ledger.scopes_digest,ledger.resource_digest
           FROM host_grant_replay_ledger ledger JOIN host_grant_audit audit
             ON audit.deployment_namespace=ledger.deployment_namespace
            AND audit.issuer=ledger.issuer AND audit.jti=ledger.jti
           WHERE ledger.deployment_namespace=%s AND ledger.issuer=%s AND ledger.jti=%s
             AND ledger.host_app_id=%s AND ledger.namespace_id=%s AND ledger.algorithm=%s
             AND ledger.grant_digest=%s AND audit.audit_id=%s AND audit.outcome='accepted'
             AND audit.grant_digest=ledger.grant_digest''',
        (namespace, proof.authority_issuer, proof.grant_id, context.host_app_id,
         context.namespace_id, proof.algorithm, proof.grant_digest, proof.audit_id),
    ).fetchone()
    digest = lambda values: sha256('\x1f'.join(sorted(values)).encode()).hexdigest()
    if (evidence is None or evidence['expires_at'] != proof.expires_at
        or evidence['scopes_digest'] != digest(context.scopes)
        or evidence['resource_digest'] != digest(f'{r.resource_type}:{r.resource_id}' for r in context.resource_refs)):
        raise HttpInputAuthorityError('HTTP input lacks committed verified grant evidence')
    now = connection.execute('SELECT clock_timestamp() AS now').fetchone()['now']
    try:
        require_task_host_context(binding, context, task_id=authority.task_id, now=now,
                                  authority_issuer=proof.authority_issuer)
    except ValueError as error:
        raise HttpInputAuthorityError('HTTP input current Task authority rejected') from error
    return now


def prepare_http_input(objects, namespace, authority, event, attachments):
    if len(attachments) > 4 or len({a.attachment_id for a in attachments}) != len(attachments):
        raise ValueError('HTTP input accepts at most four distinct attachments')
    entries = []
    for attachment in attachments:
        request = ArtifactReserveRequest(
            artifact_id=attachment.attachment_id, session_id=event.session_id,
            intended_event_sequence=event.sequence, kind=attachment.source_type,
            mime_type=attachment.media_type, sha256=sha256(attachment.payload).hexdigest(),
            size_bytes=len(attachment.payload), idempotency_key=f'http-input:{event.event_id}:{attachment.attachment_id}',
            file_name=attachment.file_name, created_at=event.created_at,
        )
        expected = ArtifactObjectExpectation(deployment_namespace=namespace,
            artifact_id=request.artifact_id, sha256=request.sha256, size_bytes=request.size_bytes)
        try:
            receipt = objects.put_if_absent(ArtifactObjectPutRequest(expectation=expected, payload=attachment.payload))
        except Exception:
            # Lost ACK is not evidence of absence; never delete an unknown put.
            verification = objects.verify(expected)
            if verification.receipt is None:
                raise
            receipt = verification.receipt
        if receipt.expectation != expected:
            raise ValueError('HTTP input object receipt conflicts')
        fields = {k: getattr(attachment, k, None) for k in (
            'original_media_type','original_size_bytes','original_sha256','page_count','paragraph_count',
            'worksheet_count','cell_count','slide_count','extraction_status','source_server','source_id')}
        reference = SessionAttachmentRef(
            attachment_id=request.artifact_id, message_event_id=event.event_id,
            file_name=attachment.file_name, media_type=attachment.media_type,
            size_bytes=request.size_bytes, sha256=request.sha256, source_type=attachment.source_type,
            source_argument_names=getattr(attachment, 'source_argument_names', ()),
            image_width=attachment.width if isinstance(attachment, ImageAttachmentInput) else None,
            image_height=attachment.height if isinstance(attachment, ImageAttachmentInput) else None, **fields)
        entries.append(PreparedHttpInputAttachment(reference, request, receipt))
    batch = PreparedHttpInputBatch(authority, event.session_id, event.event_id, tuple(entries))
    return attach_refs_to_user_event(event, tuple(e.reference for e in entries)), batch


def admit_http_input(connection, namespace, batch, event, binding):
    check_input_authority(connection, namespace, batch.authority, binding)
    if (event.actor is not EventActor.USER or event.event_type not in {
        EventType.USER_MESSAGE_RECEIVED, EventType.CLARIFICATION_RESPONDED}
        or batch.session_id != event.session_id or batch.event_id != event.event_id
        or len(batch.entries) > 4
        or len({e.reference.attachment_id for e in batch.entries}) != len(batch.entries)
        or attachment_refs_from_event(event) != tuple(e.reference for e in batch.entries)):
        raise ValueError('HTTP input batch does not match its canonical user event')
    for entry in batch.entries:
        ref, request, receipt = entry.reference, entry.reservation, entry.receipt
        expected = receipt.expectation
        if (ref.message_event_id != event.event_id or request.session_id != event.session_id
            or request.intended_event_sequence != event.sequence
            or ref.attachment_id != request.artifact_id or expected.artifact_id != request.artifact_id
            or expected.deployment_namespace != namespace or expected.sha256 != ref.sha256
            or expected.size_bytes != ref.size_bytes or request.sha256 != ref.sha256
            or request.size_bytes != ref.size_bytes or request.mime_type != ref.media_type
            or request.file_name != ref.file_name):
            raise ValueError('HTTP input reference/receipt coordinates conflict')
        connection.execute(
            '''INSERT INTO artifact_payload_metadata (
                deployment_namespace,artifact_id,session_id,intended_event_sequence,expected_stream_revision,
                kind,mime_type,sha256,size_bytes,idempotency_key,idempotency_key_hash,request_hash,
                file_name,retained_until,lifecycle_status,lifecycle_revision,object_version,object_verified_at,
                event_id,event_sequence,artifact_uri,finalized_at,request_created_at,authority_kind,http_input_authority)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'finalized',0,%s,%s,
                       %s,%s,%s,transaction_timestamp(),%s,'http_input',%s)''',
            (namespace, request.artifact_id, request.session_id, event.sequence, event.sequence-1,
             request.kind, request.mime_type, request.sha256, request.size_bytes, request.idempotency_key,
             sha256(request.idempotency_key.encode()).hexdigest(), canonical_artifact_reserve_hash(namespace, request),
             request.file_name, request.retained_until, receipt.object_version, receipt.verified_at,
             event.event_id, event.sequence, f'artifact://{request.artifact_id}', request.created_at,
             Jsonb(batch.authority.model_dump(mode='json'))),
        )


class PostgresHttpInputAdmission:
    def __init__(self, dsn, *, deployment_namespace, objects):
        from agent_storage.postgres.database import PostgresDatabase
        self.database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self.objects = objects

    def prepare(self, authority, binding, event, attachments):
        with self.database.connect() as connection:
            check_input_authority(connection, self.database.deployment_namespace, authority, binding)
        return prepare_http_input(self.objects, self.database.deployment_namespace, authority, event, attachments)

