#!/usr/bin/env python3
"""Runnable assertions. Default: no database writes. --fixture commands: QA only.

Run with Python stdlib, then in exact pinned105 API image for psycopg SQL checks.
The explicitly disposable fixture phases require dedicated QA databases and native
pg_dump/psql pre/postdata between phases; see ERP_DATABASE_TRANSFER.md.
"""
import contextlib
import copy
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import sys
import tempfile

import transfer_erp_database as t


def refuses(fn,code):
    try:
        fn()
    except t.Refusal as error:
        assert str(error)==code,(str(error),code)
    else:
        raise AssertionError('accepted '+code)


def sample_catalog():
    tables=[]
    for name in t.TABLES:
        cols=[{'name':'id','generated':'','identity':''}]
        if name in t.DEFINITIONS:
            cols.extend({'name':c,'generated':'','identity':''} for c in ('namespace_id','authority_issuer'))
        elif name!='zebra_schema_migrations':
            cols.append({'name':'deployment_namespace','generated':'','identity':''})
        if name=='governed_memory_records':
            cols.append({'name':'search_vector','generated':'s','identity':''})
        tables.append({'name':name,'columns':cols,'kind':'r','partition':False,'pk':['id'],'rls':False,'force_rls':False})
    return {'tables':tables,'views':[{'name':'task_replay_coverage_privacy','definition':'SELECT 1'}],
      'other_relations':[],'routines':[{'name':n,'security_definer':False} for n in t.ROUTINES],
      'triggers':[{'table':a,'name':b} for a,b in t.TRIGGERS],'policies':[],'user_types':[],
      'sequences':[dict(name=a+'_seq',table=a,column=b,start=1,increment=1,min=1,max=100,cycle=False) for a,b in sorted(t.SEQUENCE_OWNERS)],
      'extensions':[{'name':'plpgsql','version':'1.0'}],'constraints':[{'validated':True}],'indexes':[{'valid':True,'ready':True}]}


def checks():
    assert "'address',host(inet_server_addr())" in t.IDENTITY_SQL and 'inet_server_addr()::text' not in t.IDENTITY_SQL
    m=sample_catalog()
    t.validate_catalog(m)
    cases=[('relation_inventory',lambda x:x['tables'].append(copy.deepcopy(x['tables'][0]))),
      ('relation_inventory',lambda x:x['tables'][0].update(name='foreign_tenant')),
      ('table_shape',lambda x:x['tables'][0].update(pk=[])),
      ('primary_key',lambda x:x['tables'][0].update(pk=['missing'])),
      ('table_shape',lambda x:x['tables'][0].update(partition=True)),
      ('generated_inventory',lambda x:x['tables'][0]['columns'][0].update(generated='s')),
      ('view_inventory',lambda x:x['views'][0].update(name='unknown_view')),
      ('sequence_inventory',lambda x:x['sequences'][0].update(column='unknown')),
      ('sequence_parameters',lambda x:x['sequences'][0].update(cycle=True)),
      ('routine_inventory',lambda x:x['routines'][0].update(security_definer=True)),
      ('trigger_inventory',lambda x:x['triggers'].pop()),
      ('invalid_schema',lambda x:x['indexes'][0].update(valid=False)),
      ('invalid_schema',lambda x:x['constraints'][0].update(validated=False))]
    for code,change in cases:
        altered=copy.deepcopy(m);change(altered)
        refuses(lambda:t.validate_catalog(altered),code)
    seq=m['sequences'][0]
    assert t.next_sequence(seq,None)==(1,False)
    assert t.next_sequence(seq,1)==(1,True)
    assert t.next_sequence(seq,99)==(99,True)
    refuses(lambda:t.next_sequence(seq,100),'sequence_exhausted')
    assert t.NAMESPACES==('erpnext','erpnext-history','erpnext-continuation')
    assert t.DEFINITION==('erpnext','https://erpnext.zebra.local')
    expected=[(v,'migration_'+str(v),'a'*64) for v in list(range(1,104))+[105]]
    t.validate_ledger(expected,expected)
    for field,value in ((0,104),(1,'changed_native_name'),(2,'b'*64)):
        altered=[list(r) for r in expected];altered[0][field]=value
        refuses(lambda:t.validate_ledger(altered,expected),'source_ledger_not_canonical105')
    # The approval comparison precedes every target connection or mutation.
    worker=object.__new__(t.Worker);worker.phase='snapshot'
    worker.manifest={'catalog':m,'migrations':[[105,'native','a'*64]]};worker.hashes={'agent_tasks':{'count':1,'sha256':'b'*64}}
    for change in ('pk','generated','version','checksum','count','hash'):
        approved={'manifest':copy.deepcopy(worker.manifest),'hashes':copy.deepcopy(worker.hashes)}
        if change=='pk': approved['manifest']['catalog']['tables'][0]['pk']=['deployment_namespace']
        if change=='generated': approved['manifest']['catalog']['tables'][0]['columns'][0]['generated']='s'
        if change=='version': approved['manifest']['migrations'][0][0]=106
        if change=='checksum': approved['manifest']['migrations'][0][2]='c'*64
        if change=='count': approved['hashes']['agent_tasks']['count']=2
        if change=='hash': approved['hashes']['agent_tasks']['sha256']='d'*64
        refuses(lambda:worker.target(approved),'approval_drift')
    # Target trust boundaries fail before a target commit or DDL.
    class AuthenticationFailure(Exception):
        sqlstate='28P01'
    class FakePG:
        OperationalError=AuthenticationFailure
        def connect(self,**kwargs): raise AuthenticationFailure('private authentication detail')
    class Target:
        def __init__(self,attrs): self.attrs=attrs;self.commits=0
        def execute(self,*args): return self
        def fetchone(self): return self.attrs
        def commit(self): self.commits+=1
    source={'database':'zebra','role':'zebra','address':'172.20.0.2'}
    identity={'database':'erp_destination','role':'erp_owner','owner':'erp_owner','address':'172.21.0.2'}
    for code,mutate in (
        ('destination_identity',lambda w,i,a,x:i.update(database='wrong')),
        ('distinct_server',lambda w,i,a,x:i.update(address=source['address'])),
        ('destination_privilege',lambda w,i,a,x:a.__setitem__(0,True)),
        ('destination_membership',lambda w,i,a,x:x.update(members=1)),
        ('role_present_on_source',lambda w,i,a,x:x.update(source_roles=1)),
        ('destination_nonempty',lambda w,i,a,x:x.update(objects=1))):
        w=object.__new__(t.Worker);w.phase='snapshot';w.manifest={'source':source};w.hashes={};w.alive=lambda:None;w.quiescence=lambda:None;w.pg=FakePG()
        w.cfg={'source':{'host':source['address'],'dbname':'zebra'},'destination':{'dbname':'erp_destination','user':'erp_owner','password':'secret'},'target_address':'172.21.0.2','source_address':source['address']}
        w.src=object();info=dict(identity);attrs=[False]*5+[True];extra={'members':0,'source_roles':0,'objects':0}
        mutate(w,info,attrs,extra);target=Target(tuple(attrs));w.connect=lambda which:target;w.identity=lambda conn:info
        def count(conn,query,args=None):
            if 'pg_auth_members' in query:return extra['members']
            if 'pg_roles WHERE rolname=%s' in query:return extra['source_roles']
            return extra['objects']
        w.one=count
        refuses(lambda:w.target({'manifest':w.manifest,'hashes':w.hashes}),code)
        assert target.commits==0
    with tempfile.TemporaryDirectory() as directory:
        h=object.__new__(t.Host);h.run_directory=Path(directory);h.phase='test';h.host_identity={'docker_engine':'test'};commands=[]
        h.preflight=lambda transfer:None;h.start_worker=lambda:None;h.close=lambda:None
        def command(name,**kwargs):
            commands.append(name);return {'snapshot':'0001-0001-1'}
        h.command=command
        result=h.execute('inspect')
        assert commands==['open_snapshot','abort'] and result['destination_mutations'] is False
    # Exercise real start_worker command construction: create must keep stdin open.
    with tempfile.TemporaryDirectory() as directory:
        h=object.__new__(t.Host);h.run_directory=Path(directory);h.source_network='source-network';h.source_address='172.20.0.2';h.target_address='172.21.0.2';h.disposable_qa=False;h.log=io.BytesIO()
        h.cfg={'source':{'password':'source-secret'},'destination':{'password':'destination-secret'},'destination_network':'target-network'}
        commands=[];attached=[]
        def docker(args):
            commands.append(args)
            return b'c'*64 if args[:2]==['docker','create'] else b''
        h.run=docker
        original_popen=t.subprocess.Popen;original_file=t.__dict__.get('__file__')
        source=h.run_directory/'source.py';source.write_text('# plain maintenance entrypoint\n')
        t.__file__=str(source)
        def popen(args,**kwargs):attached.append((args,kwargs));return object()
        t.subprocess.Popen=popen
        try:h.start_worker()
        finally:
            t.subprocess.Popen=original_popen
            if original_file is None:t.__dict__.pop('__file__',None)
            else:t.__file__=original_file
        create=commands[0]
        assert create[:3]==['docker','create','--interactive']
        assert create[create.index('--entrypoint')+1]=='/app/.venv/bin/python' and t.API_IMAGE in create
        assert commands[1]==['docker','network','connect','target-network','c'*64]
        assert attached[0][0]==['docker','start','--attach','--interactive','c'*64]
        assert 'source-secret' not in ' '.join(create) and 'destination-secret' not in ' '.join(create)
        assert t.secure_read(h.run_directory/'worker.json') and (h.run_directory/'worker.py').exists()
    # A COPY failure never commits partial data or claims activation.
    class Destination:
        def __init__(self): self.commits=self.rollbacks=0
        def commit(self): self.commits+=1
        def rollback(self): self.rollbacks+=1
    worker.phase='pre_restored';worker.sql=None;worker.durable=['pre_data'];worker.dst=Destination();worker.alive=lambda:None
    def fail(table): raise RuntimeError('row data and password must stay private')
    worker.copy_table=fail
    try: worker.copy_rows()
    except RuntimeError: pass
    else: raise AssertionError('COPY failure swallowed')
    assert worker.dst.commits==0 and worker.dst.rollbacks==1 and worker.durable==['pre_data']
    # Worker protocol discards raw exception text while retaining phase/SQLSTATE.
    original=t.Worker
    class FailedWorker:
        phase='pre_restored';durable=['pre_data']
        def __init__(self,cfg): pass
        def copy_rows(self):
            error=RuntimeError('postgresql://secret:user@host/ row=private')
            error.sqlstate='23505';raise error
        def abort(self): pass
    with tempfile.TemporaryDirectory() as directory:
        Path(directory).chmod(0o700);cfg=Path(directory)/'config';t.secure_write(cfg,b'{}')
        oldin=sys.stdin;out=io.StringIO();sys.stdin=io.StringIO('{"command":"copy_rows"}\n');t.Worker=FailedWorker
        try:
            with contextlib.redirect_stdout(out): t.worker_main(str(cfg))
        finally: sys.stdin=oldin;t.Worker=original
        response=json.loads(out.getvalue());assert response['sqlstate']=='23505' and response['reason']=='worker_failure' and 'secret' not in out.getvalue() and 'private' not in out.getvalue()
        cfg.chmod(0o644);refuses(lambda:t.secure_read(cfg),'protected_file_mode')
    with tempfile.TemporaryDirectory() as directory:
        h=object.__new__(t.Host);h.run_directory=Path(directory);h.process=None;h.container='temporary-only';h.log=io.BytesIO()
        secret=h.run_directory/'worker.json';t.secure_write(secret,b'private')
        def cleanup_failure(args):raise t.Refusal('native_command_failed')
        h.run=cleanup_failure
        refuses(h.close,'maintenance_cleanup_incomplete')
        assert h.cleanup_report['maintenance_container_absent'] is False
        assert not secret.exists() and h.log.closed
    with tempfile.TemporaryDirectory() as directory:
        h=object.__new__(t.Host);h.run_directory=Path(directory);h.process=None;h.container='temporary-only';h.log=io.BytesIO();h.phase='copy_rows'
        secret=h.run_directory/'worker.json';t.secure_write(secret,b'private')
        h.preflight=lambda transfer:None
        def primary_failure():raise t.Refusal('original_transfer_failure')
        h.start_worker=primary_failure;h.run=cleanup_failure
        refuses(lambda:h.execute('inspect'),'original_transfer_failure')
        assert not secret.exists() and h.cleanup_report['maintenance_container_absent'] is False
        assert (h.run_directory/'INCOMPLETE.json').exists() and (h.run_directory/'CLEANUP_INCOMPLETE.json').exists()
    class FailedProcess:
        class Input:
            def close(self):raise OSError('private detail')
        stdin=Input()
        def poll(self):return None
        def terminate(self):raise OSError('private detail')
    with tempfile.TemporaryDirectory() as directory:
        h=object.__new__(t.Host);h.run_directory=Path(directory);h.process=FailedProcess();h.container='temporary-only';h.log=io.BytesIO()
        secret=h.run_directory/'worker.json';t.secure_write(secret,b'private');removed=[];h.run=lambda args:removed.append(args)
        refuses(h.close,'maintenance_cleanup_incomplete')
        assert removed and not secret.exists() and h.cleanup_report['maintenance_container_absent'] is True
        assert h.cleanup_report['errors']==['attach_process_termination_failed']
    class AbortConnection:
        def __init__(self,fail=False):self.closed=False;self.fail=fail
        def rollback(self):
            if self.fail:raise RuntimeError('private network detail')
        def close(self):self.closed=True
    w=object.__new__(t.Worker);first=AbortConnection(True);second=AbortConnection();w.dst=first;w.src=second;w.durable=[]
    refuses(w.abort,'abort_connection_failure')
    assert first.closed and second.closed and w.dst is w.src is None
    gate={'version':1,'reviewed_by_operator':'reviewer','site':'erpnext.zebra.local','observed_at':datetime.now(timezone.utc).isoformat(),'guard_source_commit':'a'*40,
       'admission_probe':{'http_status':417,'cloud_mutations':0,'evidence_ref':'protected/probe.json','response_sha256':'b'*64},
       'conversation_lock_drain':{'outstanding':0,'checked':9,'evidence_ref':'protected/drain.json'},
       'producer_inventory':[{'identity':'exact-container-id','kind':'worker','state':'stopped','evidence_ref':'protected/docker.json'}],'unresolved':[]}
    assert 'attestation' in t.validate_gate(gate)['assurance']
    gate['unresolved']=['unknown consumer'];refuses(lambda:t.validate_gate(gate),'operator_gate_unresolved')
    try:
        from psycopg import sql
    except ImportError:
        print('PASS stdlib assertions; psycopg SQL/roundtrip checks require pinned API image')
    else:
        actual=t.canonical_migrations()
        assert len(actual)==104 and actual[-1][:2]==(105,'scoped_plugin_installations')
        t.validate_ledger(actual)
        for field,value in ((0,104),(1,'changed_native_name'),(2,'b'*64)):
            altered=[list(r) for r in actual];altered[0][field]=value
            refuses(lambda:t.validate_ledger(altered),'source_ledger_not_canonical105')
        worker=object.__new__(t.Worker);worker.sql=sql
        table={'name':'agent_tasks','columns':[{'name':'deployment_namespace','generated':''},{'name':'id','generated':''},{'name':'odd"col','generated':''},{'name':'computed','generated':'s'}],'pk':['id']}
        query,params=worker.query(table,False);rendered=query.as_string()
        assert '"odd""col"' in rendered and 'computed' not in rendered and 'erpnext' not in rendered and params==[list(t.NAMESPACES)]
        definition={'name':'agent_definition_records','columns':[{'name':'namespace_id'},{'name':'authority_issuer'}]}
        pred,params=worker.predicate(definition);assert pred.as_string().count('%s')==2 and params==list(t.DEFINITION) and 'https://' not in pred.as_string()
        print('PASS stdlib and real psycopg identifier/value assertions')


# These are deliberately separate, explicitly QA-only phases around native dump/restore.
FIXTURE_TABLES=[{'name':'agent_tasks','pk':['deployment_namespace','id'],'columns':[{'name':n,'generated':g} for n,g in [('deployment_namespace',''),('id',''),('peer_id',''),('payload',''),('doc',''),('at',''),('computed','s')]]},
 {'name':'session_events','pk':['deployment_namespace','id'],'columns':[{'name':n,'generated':''} for n in ('deployment_namespace','id','task_id')]},
 {'name':'host_grant_audit','pk':['deployment_namespace','audit_id'],'columns':[{'name':n,'generated':''} for n in ('deployment_namespace','audit_id')]}]
FIXTURE_DDL="""
CREATE TABLE public.agent_tasks(deployment_namespace text NOT NULL,id bigint GENERATED ALWAYS AS IDENTITY,peer_id bigint,payload text,doc jsonb,at timestamptz,computed text GENERATED ALWAYS AS (upper(payload)) STORED,PRIMARY KEY(deployment_namespace,id));
CREATE TABLE public.session_events(deployment_namespace text NOT NULL,id bigint PRIMARY KEY,task_id bigint);
ALTER TABLE public.agent_tasks ADD CONSTRAINT fixture_cycle_a FOREIGN KEY(peer_id) REFERENCES public.session_events(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE public.session_events ADD CONSTRAINT fixture_cycle_b FOREIGN KEY(deployment_namespace,task_id) REFERENCES public.agent_tasks(deployment_namespace,id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE public.host_grant_audit(deployment_namespace text NOT NULL,audit_id bigserial PRIMARY KEY);
CREATE VIEW public.task_replay_coverage_privacy AS SELECT deployment_namespace,id FROM public.agent_tasks;
"""


def fixture(mode,path):
    import psycopg
    from psycopg import sql
    cfg=json.loads(t.secure_read(path))
    require_db=lambda c,prefix:t.require(c['dbname'].startswith(prefix),'fixture_database_identity')
    require_db(cfg['source'],'zebra_transfer_qa_source_');require_db(cfg['destination'],'erpnext_agent_qa_')
    t.require(cfg['source']['host']!=cfg['destination']['host'],'fixture_distinct_endpoints')
    worker=t.Worker(cfg)
    worker.src=worker.connect('source');worker.dst=worker.connect('destination')
    try:
        if mode=='identity':
            for name,conn in (('source',worker.src),('destination',worker.dst)):
                conn.execute('SET TRANSACTION READ ONLY')
                info=worker.identity(conn)
                assert info['address']==cfg[name]['host'] and '/' not in info['address']
                assert info['database']==cfg[name]['dbname'] and info['role']==cfg[name]['user']
            print('PASS real native host(inet_server_addr()) identity matches exact configured server addresses')
        elif mode=='prepare':
            for c in (worker.src,worker.dst):
                t.require(c.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'").fetchone()[0]==0,'fixture_database_nonempty')
            worker.src.execute(FIXTURE_DDL)
            worker.src.execute("INSERT INTO public.agent_tasks(deployment_namespace,id,peer_id,payload,doc,at) OVERRIDING SYSTEM VALUE VALUES(%s,42,7,%s,%s,%s)",['erpnext','tabs\tnewlines\nbackslash\\ literal\\N',json.dumps({'null':None,'line':'a\nb','unicode':'中文'}),'2026-10-23 12:34:56.123456+08'])
            worker.src.execute("INSERT INTO public.agent_tasks(deployment_namespace,id,payload) OVERRIDING SYSTEM VALUE VALUES ('erpnext-history',43,NULL),('erpnext-continuation',44,'\\N')")
            worker.src.execute("INSERT INTO public.session_events VALUES('erpnext',7,42)")
            worker.src.commit()
            print('PASS disposable fixture prepared; source data exists only in labeled QA server')
        elif mode in ('copy','verify'):
            worker.src.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            expected={tb['name']:worker.row_hash(worker.src,tb) for tb in FIXTURE_TABLES}
            if mode=='copy':
                # Reuse production transaction/error boundary, then prove injected failure rolled back.
                worker.manifest={'catalog':{'tables':FIXTURE_TABLES}};worker.phase='pre_restored';worker.alive=lambda:None
                original=worker.copy_table;calls=[]
                def failing(table):
                    calls.append(table['name'])
                    if len(calls)==2: raise RuntimeError('injected mid-copy failure')
                    original(table)
                worker.copy_table=failing
                try: worker.copy_rows()
                except RuntimeError: pass
                else: raise AssertionError('injected failure absent')
                assert not worker.durable and all(worker.row_hash(worker.dst,tb)['count']==0 for tb in FIXTURE_TABLES)
                worker.dst.rollback();worker.copy_table=original
                worker.copy_rows()
                assert {tb['name']:worker.row_hash(worker.dst,tb) for tb in FIXTURE_TABLES}==expected
                worker.dst.rollback()
                print('PASS text COPY and rollback injection; restore native post-data next')
            else:
                assert {tb['name']:worker.row_hash(worker.dst,tb) for tb in FIXTURE_TABLES}==expected
                # Generated-column changes must be visible in the canonical full-row hash.
                table=FIXTURE_TABLES[0];before=worker.row_hash(worker.dst,table)
                worker.dst.execute("ALTER TABLE public.agent_tasks DROP COLUMN computed; ALTER TABLE public.agent_tasks ADD COLUMN computed text GENERATED ALWAYS AS (lower(payload)) STORED")
                assert worker.row_hash(worker.dst,table)!=before
                worker.dst.rollback()
                assert worker.dst.execute("SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated").fetchone()[0]==0
                assert worker.dst.execute("SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relnamespace='public'::regnamespace AND (NOT indisvalid OR NOT indisready)").fetchone()[0]==0
                for table,column in (('agent_tasks','id'),('host_grant_audit','audit_id')):
                    seq=worker.dst.execute('SELECT pg_get_serial_sequence(%s,%s)',['public.'+table,column]).fetchone()[0]
                    maximum=worker.dst.execute(sql.SQL('SELECT max({}) FROM {}').format(sql.Identifier(column),sql.Identifier('public',table))).fetchone()[0]
                    value,called=t.next_sequence({'start':1,'increment':1,'min':1,'max':2**63-1,'cycle':False},maximum)
                    worker.dst.execute('SELECT setval(%s::regclass,%s,%s)',[seq,value,called])
                    observed=worker.dst.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier('public',seq.split('.')[-1]))).fetchone()
                    assert observed==(value,called)
                worker.dst.commit()
                print('PASS native cyclic FK/identity/generated/hash and empty/nonempty sequence roundtrip')
        else:
            raise ValueError('unknown fixture phase')
    finally:
        worker.abort()


if __name__=='__main__':
    if len(sys.argv)==1: checks()
    else:
        assert len(sys.argv)==4 and sys.argv[1]=='--fixture' and sys.argv[2] in ('identity','prepare','copy','verify')
        fixture(sys.argv[2],sys.argv[3])
