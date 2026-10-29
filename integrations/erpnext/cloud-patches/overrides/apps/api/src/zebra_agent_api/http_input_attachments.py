"""Convert only native consumed Host verification into typed input authority."""
from datetime import UTC, datetime
from agent_core.domain.http_input_attachments import HttpInputAuthority
from agent_core.domain.task_bindings import TaskBindingSnapshot, require_task_host_context
from agent_security.host_grant import VerifiedHostGrant


def verified_input_authority(verified, binding):
    if not isinstance(verified, VerifiedHostGrant) or verified.consumed_proof is None:
        raise ValueError('HTTP attachments require consumed native Host grant evidence')
    if not isinstance(binding, TaskBindingSnapshot):
        raise ValueError('HTTP attachments require the native Task binding')
    verified.context.require_scope('agent.run')
    require_task_host_context(binding, verified.context, task_id=str(binding.task_id),
                              now=datetime.now(UTC), authority_issuer=verified.authority_issuer)
    return HttpInputAuthority(context=verified.context, proof=verified.consumed_proof,
        task_id=str(binding.task_id), binding_digest=binding.binding_digest)


from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import ArtifactId, EventId, SessionId, TaskId
from agent_core.domain.http_input_messages import PreparedHttpInputMessage
from agent_storage.postgres.http_input_attachments import HttpInputAuthorityError, check_input_authority
from agent_storage.postgres.http_input_messages import append_http_input
from agent_storage.postgres.task_admission import load_task_binding
from zebra_agent_api.idempotency import request_hash, scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_payloads import parse_append_session_message_payload


@dataclass(frozen=True)
class HttpInputIntent:
    admission: object
    binding: object
    authority: HttpInputAuthority
    parsed: dict
    action: str
    key: str
    digest: str

    def prepare(self, session_id, sequence, created_at):
        identity=f'{self.authority.proof.deployment_namespace}:{self.authority.task_id}:{self.key}:{self.digest}'
        event_id=EventId(uuid5(NAMESPACE_URL,'zebra-http-input-event:'+identity))
        fields={key:self.parsed[key] for key in ('content','clarification_id','model_profile','reasoning_effort')
                if self.parsed.get(key) is not None}
        event=SessionEvent(session_id=SessionId(UUID(str(session_id))),sequence=sequence,
            event_id=event_id,event_type=EventType.CLARIFICATION_RESPONDED if self.parsed.get('clarification_id') else EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,payload=fields,created_at=created_at)
        attachments=tuple(item.model_copy(update={'attachment_id':ArtifactId(uuid5(NAMESPACE_URL,
            f'zebra-http-input-file:{identity}:{index}'))}) for index,item in enumerate(self.parsed['attachments']))
        event,batch=self.admission.prepare(self.authority,self.binding,event,attachments)
        return PreparedHttpInputMessage(event,batch,self.action,self.key,self.digest)


def _receipt(app, action, key, digest):
    record=app.stores.idempotency.get(action=action,idempotency_key=key)
    if record is None:return None
    if record.request_hash != digest:
        return ApiResponse(409,{'status':'idempotency_conflict'})
    if not record.response_body:
        return ApiResponse(409,{'status':'http_input_reconciliation_required'})
    return ApiResponse(record.status_code,record.response_body)


def append_cloud_input(app, task_id, payload, *, verified_host_grant, idempotency_key, explicit_session=None):
    if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>255:
        return ApiResponse(400,{'status':'http_input_idempotency_key_required'})
    if not isinstance(verified_host_grant,VerifiedHostGrant) or verified_host_grant.consumed_proof is None:
        return ApiResponse(403,{'status':'http_input_authority_required'})
    try:task_id=TaskId(UUID(str(task_id)))
    except ValueError:return ApiResponse(400,{'status':'invalid_task_id'})
    admission=getattr(app.stores,'http_input_admission',None)
    if admission is None:return ApiResponse(503,{'status':'http_input_admission_unavailable'})
    database=admission.database
    binding=load_task_binding(database._dsn,deployment_namespace=database.deployment_namespace,task_id=task_id)
    try:
        authority=verified_input_authority(verified_host_grant,binding)
        with database.connect() as connection:
            check_input_authority(connection,database.deployment_namespace,authority,binding)
    except ValueError:return ApiResponse(403,{'status':'http_input_authority_rejected'})
    key=scoped_idempotency_key(idempotency_key,verified_host_grant.context)
    action=f'http-input:{task_id}'
    digest=request_hash(payload)
    replay=_receipt(app,action,key,digest)
    if replay is not None:return replay
    parsed=parse_append_session_message_payload(payload,allow_clarification_attachments=True)
    if isinstance(parsed,ApiResponse):return parsed
    task=app.stores.tasks.get_task(task_id)
    if task is None:return ApiResponse(404,{'status':'not_found'})
    if explicit_session is not None and str(task.active_segment_id)!=str(explicit_session):
        return ApiResponse(409,{'status':'http_input_active_segment_changed'})
    session=app.stores.sessions.get_session(task.active_segment_id)
    if session is None:return ApiResponse(409,{'status':'projection_incomplete'})
    if parsed.get('clarification_id') and parsed['attachments']:
        from agent_core.application.session_attachments import attachment_refs_from_event, validate_attachment_context_budget
        history=app.stores.events.list_for_session(session.session_id)
        original=next((item for item in reversed(history) if item.event_type is EventType.USER_MESSAGE_RECEIVED),None)
        refs=tuple(ref for item in history if original is not None and item.sequence>=original.sequence
                   for ref in attachment_refs_from_event(item))
        try:validate_attachment_context_budget((*refs,*parsed['attachments']))
        except ValueError:return ApiResponse(400,{'status':'attachment_turn_limit_exceeded'})
    history=app.stores.events.list_for_session(session.session_id)
    options={}
    for item in history:
        if item.event_type in {EventType.USER_MESSAGE_RECEIVED,EventType.TASK_PREPARED}:
            options.update({name:item.payload[name] for name in ('model_profile','reasoning_effort')
                            if item.payload.get(name) is not None})
    if not parsed.get('clarification_id'):
        options.update({name:parsed[name] for name in ('model_profile','reasoning_effort') if parsed.get(name) is not None})
        if (options.get('model_profile') not in {'deepseek-v4-flash-executor-v1','deepseek-v4-pro-executor-v1'}
            or options.get('reasoning_effort') not in {'none','low','high','max'}):
            return ApiResponse(409,{'status':'http_input_model_options_unresolved'})
        # Pin inherited options into the new canonical event, including child
        # Segments; request_hash above still describes the original wire body.
        parsed={**parsed,**options}
    if any(item.media_type.startswith('image/') for item in parsed['attachments']):
        if options.get('model_profile')!='deepseek-v4-flash-executor-v1':
            return ApiResponse(400,{'status':'image_requires_flash_input_profile'})
    intent=HttpInputIntent(admission,binding,authority,parsed,action,key,digest)
    try:
        if session.status.value in {'completed','cancelled','failed'}:
            if parsed.get('clarification_id'):
                return ApiResponse(409,{'status':'no_active_clarification'})
            from agent_core.domain.session_handoff import HandoffActorKind
            from zebra_agent_api.session_handoff import SessionHandoffApi
            response=SessionHandoffApi(app.database_path,app.stores).create(str(task.active_segment_id),
                dict(title=session.title,objective=parsed['content'],stage_prompt='Continue from the verified Task checkpoint.',
                     reason='internal_terminal_follow_up' if session.status.value=='completed' else 'internal_recovery'),
                idempotency_key=f'http-input-rollover:{key}',principal_identity_hash=sha256(f'task:{task_id}'.encode()).hexdigest(),
                actor_kind=HandoffActorKind.AUTOMATION,http_input=intent)
            if response.status_code not in {200,201}:return response
            return _receipt(app,action,key,digest) or ApiResponse(503,{'status':'http_input_receipt_unavailable'})
        from zebra_agent_api.session_message_submission import build_session_message_event
        draft=build_session_message_event(event_store=app.stores.events,session=session,
            content=parsed['content'],clarification_id=parsed['clarification_id'],
            model_profile=parsed['model_profile'],reasoning_effort=parsed['reasoning_effort'])
        prepared=intent.prepare(session.session_id,draft.sequence,draft.created_at)
        receipt=append_http_input(database,prepared)
        return ApiResponse(receipt.status_code,receipt.response_body)
    except HttpInputAuthorityError:return ApiResponse(403,{'status':'http_input_authority_rejected'})
    except ValueError:return ApiResponse(409,{'status':'http_input_revision_or_turn_conflict'})


def has_raw_input_attachments(payload):
    if not isinstance(payload,dict):return False
    if 'attachments' in payload or 'attachment_refs' in payload:return True
    value=payload.get('input')
    if not isinstance(value,dict):return False
    if 'attachments' in value or 'attachment_refs' in value:return True
    messages=value.get('messages')
    if not isinstance(messages,list):return False
    for message in messages:
        if not isinstance(message,dict):continue
        if 'attachments' in message or 'attachment_refs' in message:return True
        content=message.get('content')
        if isinstance(content,list) and any(isinstance(part,dict) and part.get('type') in {'binary','image','file'} for part in content):
            return True
    return False
