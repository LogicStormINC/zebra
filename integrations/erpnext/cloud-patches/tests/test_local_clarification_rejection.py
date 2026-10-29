"""Native SQLite compatibility: local clarification files reject before writes."""
import overlay_imports
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from agent_core.application import SessionBootstrapCommand,SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventType,EventActor,SessionEvent
from zebra_agent_api import create_app
from zebra_agent_api.session_payloads import parse_append_session_message_payload
from zebra_agent_api.responses import ApiResponse

payload=dict(content='yes',clarification_id='qa',attachments=[dict(file_name='a.txt',media_type='text/plain',content_base64='eWVz')])
assert isinstance(parse_append_session_message_payload(payload),ApiResponse)
assert isinstance(parse_append_session_message_payload(payload,allow_clarification_attachments=True),dict)
with TemporaryDirectory() as directory:
    path=Path(directory)/'native.sqlite'
    app=create_app(path)
    boot=SessionBootstrapService().build(SessionBootstrapCommand(title='QA',user_input='original',workspace_root=directory))
    events=list(boot.events);sid=boot.session.session_id
    events.append(SessionEvent.create(session_id=sid,sequence=len(events),event_type=EventType.HARNESS_ATTEMPT_STARTED,actor=EventActor.HARNESS,payload={'attempt_number':1}))
    events.append(SessionEvent.create(session_id=sid,sequence=len(events),event_type=EventType.CLARIFICATION_REQUESTED,actor=EventActor.HARNESS,
        payload=dict(clarification_id='qa',tool_call_id='qa',question='Which?',assistant_message='Choose',choices=['yes','no'],
                     attempt_number=1,conversation=[],model_calls_used=1,tool_calls_executed=0)))
    for event in events:app.stores.events.append(event)
    app.stores.sessions.save_session(rebuild_session(events));app.stores.workspaces.save_workspace(rebuild_workspace(events))
    before_session=app.stores.sessions.get_session(sid);before_workspace=app.stores.workspaces.get_workspace(sid)
    def counts():
        with sqlite3.connect(path) as connection:
            tables=[row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {table:connection.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}
    before_counts=counts();calls=[]
    store_type=type(app.stores.artifact_payloads);original=store_type.store_payload
    def forbidden(*args,**kwargs):calls.append(True);raise AssertionError('Local rejected file reached payload storage')
    store_type.store_payload=forbidden
    try:response=app.append_session_message(str(sid),payload)
    finally:store_type.store_payload=original
    assert response.status_code==400,response.body
    assert response.body['reason']=='clarification responses do not accept attachments'
    assert not calls and counts()==before_counts
    assert app.stores.events.list_for_session(sid)==events
    assert app.stores.sessions.get_session(sid)==before_session
    assert app.stores.workspaces.get_workspace(sid)==before_workspace
print('PASS actual SQLite WAITING_INPUT rejects clarification file400, unchanged events/projections/all table counts, zero payload writes; explicit Cloud parser opt-in accepts')
