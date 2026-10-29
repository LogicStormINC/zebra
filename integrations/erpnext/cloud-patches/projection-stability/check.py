"""One deterministic check of the actual targeted projection loop, no model/DB writes."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
import sys


def check(path):
    tree=ast.parse(Path(path).read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_chat_projection')
    fn.body=[n for n in fn.body if not isinstance(n,ast.ImportFrom)]
    calls=[]
    class Stop:
        tick=0
        def is_set(self):return self.tick>=3
        def wait(self,_):self.tick+=1
    stop=Stop()
    class Connection:
        def execute(self,sql,args=()):
            assert sql.startswith(('SELECT','SET TRANSACTION READ ONLY'))
            self.args=args;self.query=sql
            return self
        def fetchone(self):return None if self.args[-1]=='old' else {'session_id':'session-'+self.args[-1]}
        def fetchall(self):
            assert 'native_version(t)' in self.query
            assert self.args[-2]==self.args[-1]
            return [{'task_id':'missing'}] if stop.tick==0 and self.args[-1]=='ag-ui-v1' else []
    class DB:
        @contextmanager
        def connect_task_io(self):yield Connection()
    policy=NS(_database=DB(),require=lambda session:calls.append(('authorize',session)))
    class Work:
        _version="ag-ui-v1"
        def enable_projection_work(self):calls.append(('enable',))
        def read_projection_work_repairs(self,limit=32,after_task_id=None):
            assert limit==32
            if self._version!='ag-ui-v1':return []
            calls.append(('repair_cursor',after_task_id))
            return [NS(scope=NS(task_id=x)) for x in ('dirty','old')] if stop.tick==0 else []
        def repair_projection_work(self,task,limit):
            assert task in ('dirty','missing'),'healthy native append routes must never be write-locked by repair'
            calls.append(('repair',task));return NS(needs_repair=False)
        def read_pending_projection_work(self,limit,after_scope):
            if self._version!='ag-ui-v1':return []
            return [NS(scope=NS(task_id=x)) for x in ('healthy','old')]
    consumer=NS(work=Work(),materialize_once=lambda work:calls.append(('materialize',work.scope.task_id)))
    coverage=Work();coverage._version='ag-ui-v1-coverage'
    coverage_consumer=NS(work=coverage,materialize_once=lambda _: (_ for _ in ()).throw(AssertionError('wrong projector')))
    loop=NS(_execution_service=NS(_erp_workspace_containment=policy),_projection_work=NS(consumers=[consumer,coverage_consumer]))
    scope={'HostGrantExpiredError':type('HostGrantExpiredError',(Exception,),{}),'candidate_sql':lambda _: ' AND native_generation=true','TaskId':lambda x:x,'task_version':lambda alias,postgres: 'native_version('+alias+')'}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),scope)
    scope['run_chat_projection'](loop,stop)
    assert calls.count(('repair','dirty'))==1,calls
    assert calls.count(('repair','missing'))==1,calls
    assert calls.count(('materialize','healthy'))==3,calls
    assert not any(x[0] in ('repair','materialize') and x[1]=='old' for x in calls),calls
    assert [x[1] for x in calls if x[0]=='repair_cursor']==[None,'old',None],calls
    assert calls.count(('enable',))==2,calls
    print('PASS actual loop: healthy routes not repaired; dirty queue repair; old Task refusal; cursor reset; native materialization')


if __name__=='__main__':check(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'worker/erp_chat_readonly_main.py')

# Execute the actual scalar ready dispatcher with an expired oldest Task,
# known Fresh refusal/unavailability and an already-consumed excluded Task.
from datetime import datetime, UTC
source=Path(__file__).parent/'worker/erp_chat_readonly_main.py'
fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='run_ready_chat_tick')
fn.body=[n for n in fn.body if not isinstance(n,ast.ImportFrom)]
Expired=type('Expired',(Exception,),{});Refused=type('Refused',(Exception,),{});Unavailable=type('Unavailable',(Exception,),{})
executed=[];authorized=[]
class ReadyConnection:
    def execute(self,query,args=()):
        assert query.startswith(('SELECT','SET TRANSACTION READ ONLY'))
        if query.startswith('SELECT'):
            assert 'SELECT p.session_id' in query and 'native_generation' in query
            self.after=args[1]
        return self
    def fetchall(self):return [] if self.after else [{'session_id':x} for x in ('expired','denied','unavailable','excluded','dispatch-expired','dispatch-denied','dispatch-unavailable','valid')]
class ReadyDB:
    @contextmanager
    def connect_task_io(self):yield ReadyConnection()
def authorize(sid):
    authorized.append(sid)
    if sid=='expired':raise Expired()
class Fresh:
    @staticmethod
    def for_execution(execution,sid):return NS(probe=lambda now:sid)
def early(decision):
    if decision=='denied':raise Refused()
    if decision=='unavailable':raise Unavailable()
def execute(sid,**kwargs):
    if sid=='dispatch-expired':raise Expired()
    if sid=='dispatch-denied':raise Refused()
    if sid=='dispatch-unavailable':raise Unavailable()
    executed.append((sid,kwargs))
execution=NS(_erp_workspace_containment=NS(_database=ReadyDB(),require=authorize),execute_session=execute)
scope={'candidate_sql':lambda alias:' AND native_generation=true','HostGrantExpiredError':Expired,'EarlyFreshRefusal':Refused,'EarlyFreshUnavailable':Unavailable,'FreshERPAuthority':Fresh,'require_early_authority':early,'datetime':datetime,'UTC':UTC}
exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),scope)
assert scope['run_ready_chat_tick'](execution,None,'excluded')=='valid'
assert executed==[('valid',{'worker_id':'erp-chat-readonly','lease_ttl_seconds':60})],executed
assert 'excluded' not in authorized
assert scope['run_ready_chat_tick'](execution,'valid',None) is None
print('PASS actual ready dispatcher: expired/denied/unavailable skipped without execution; later valid work runs; scalar gate and cursor reset')
