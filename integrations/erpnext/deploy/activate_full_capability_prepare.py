"""Prepare new durable production services; leave ERP/legacy/Search untouched."""
import base64
import json
import os
from pathlib import Path
import secrets
import time
from activate_full_capability import *

PG='sha256:5d004e058f520673f1f6edbad6b1603d5dab4c818e257c041889ef64672a8cc4'
REDIS='sha256:7033ad495c19'
OBJECTS='sha256:a1ea29fa2835'
CADDY='sha256:ed66ea6bd84e'


def main():
    require_no_active()
    if ROOT.exists():raise ValueError('release root exists; inspect progress, never repeat blind setup')
    if NETWORK in capture('docker','network','ls','--format','{{.Name}}').splitlines():raise ValueError('production network exists')
    ROOT.mkdir(mode=0o700)
    current=json.loads(capture('docker','exec','erpnext-backend-1','cat','/home/frappe/frappe-bench/sites/192.168.110.42/site_config.json'))
    private(ROOT/'site.before.json',json.dumps(current))
    # Refresh backup immediately before the production preparation. All reads.
    for name,command in [('native105.current.dump',('docker','exec','erpnext-agent-postgres-1','pg_dump','-U','erpnext_agent','-d','erpnext_agent','-Fc')),
        ('erp.current.sql',('docker','exec','erpnext-db-1','sh','-c','exec mariadb-dump --single-transaction --skip-lock-tables --databases "$1" -uroot -p"$MYSQL_ROOT_PASSWORD"','--',current['db_name']))]:
        with (ROOT/name).open('xb') as out:run(*command,stdout=out,stderr=subprocess.DEVNULL)
        (ROOT/name).chmod(0o600)
    before={}
    for name in ['erpnext-backend-1','erpnext-frontend-1','erpnext-agent-api-1','erpnext-agent-chat-worker-1','zebra-web-search-searxng-1','zebra-yahoo-egress']:
        data=json.loads(capture('docker','inspect',name))[0]
        before[name]=dict(id=data['Id'],image=data['Image'],started=data['State']['StartedAt'],restarts=data['RestartCount'])
        if name in {'erpnext-backend-1','erpnext-frontend-1'}:private(ROOT/(name+'.inspect.json'),json.dumps(data))
    private(ROOT/'before.json',json.dumps(before,indent=2))
    # Reuse the repository's worker-only Docker CLI layer, with an existing image.
    build=ROOT/'worker-build';build.mkdir()
    (build/'Dockerfile').write_text(f'FROM {TOOLS} AS docker_cli\nFROM {NATIVE}\nCOPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker\n')
    with (ROOT/'build-worker.log').open('x') as log:
        run('docker','build','--pull=false','--network=none','-t','erpnext-full-worker:20261029',str(build),env={**os.environ,'DOCKER_BUILDKIT':'0'},stdout=log,stderr=log)
    worker=json.loads(capture('docker','image','inspect','erpnext-full-worker:20261029'))[0]['Id']
    tls=ROOT/'tls';public=ROOT/'public';tls.mkdir();public.mkdir()
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'runtime.key'),'-out',str(tls/'runtime.crt'),
        '-days','365','-subj','/CN=ERP Cloud Runtime','-addext',f'subjectAltName=DNS:{HOST},DNS:{AGENT},DNS:{SEARCH}',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (tls/'runtime.key').chmod(0o600)
    system_ca=capture('docker','run','--rm','--network','none','--entrypoint','cat',NATIVE,'/etc/ssl/certs/ca-certificates.crt')
    old_ca=Path('/opt/erpnext/zebra-agent/secrets/ca.crt').read_text()
    (public/'ca-bundle.crt').write_text(system_ca+'\n'+old_ca+'\n'+(tls/'runtime.crt').read_text())
    native_previous=json.loads(capture('docker','inspect','erpnext-agent-chat-worker-1'))[0]
    inherited=dict(v.split('=',1) for v in native_previous['Config']['Env'] if '=' in v)
    values={k:v for k,v in inherited.items() if k.startswith(('DEEPSEEK_','ZEBRA_MODEL_','ZEBRA_DEEPSEEK_','ZEBRA_PUBLIC_OUTPUT_'))}
    dbpass=secrets.token_hex(32);redispass=secrets.token_hex(32)
    access='erpfull'+secrets.token_hex(10);secret=secrets.token_urlsafe(40)
    private(ROOT/'postgres.env',f'POSTGRES_PASSWORD={dbpass}\n')
    private(ROOT/'objects.env',f'MINIO_ROOT_USER={access}\nMINIO_ROOT_PASSWORD={secret}\n')
    private(ROOT/'redis.conf','appendonly yes\nappendfsync everysec\nmaxmemory 256mb\nmaxmemory-policy noeviction\nrequirepass '+redispass+'\n')
    root('install','-d','-o','0','-g','0','-m','755','/data/erpnext-agent-full')
    for folder,uid in [('postgres','70'),('redis','999'),('objects','1000'),('workspace-volumes','0')]:
        root('install','-d','-o',uid,'-g',uid,'-m','700','/data/erpnext-agent-full/'+folder)
    root('chown','999:999',str(ROOT/'redis.conf'))
    run('docker','network','create','--internal',NETWORK,stdout=subprocess.DEVNULL)
    mcp=ROOT/'mcp';mcp.mkdir(mode=0o700)
    private(mcp/'master.json',json.dumps(dict(value=base64.b64encode(secrets.token_bytes(32)).decode(),version='1')))
    root('chown','-R','65532:65532',str(mcp))
    values.update(ZEBRA_PROFILE='cloud',ZEBRA_DEPLOYMENT='cloud',ZEBRA_STORAGE_AUTHORITY='postgresql',
        ZEBRA_DATABASE_URL=f'postgresql://erpnext_full:{dbpass}@native-full-db:5432/{DB}',ZEBRA_DEPLOYMENT_NAMESPACE='erpnext-full',
        ZEBRA_AUTHORITY_ISSUER=current['zebra_agent']['issuer'],ZEBRA_HISTORY_SCOPE_NAMESPACE='erpnext-full',ZEBRA_CONTINUATION_SCOPE_NAMESPACE='erpnext-full',
        ZEBRA_API_AUTH_TOKEN=secrets.token_urlsafe(40),ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED='true',ZEBRA_STREAM_V2_CURSOR_SIGNING_KEY=secrets.token_hex(32),
        ZEBRA_MEMORY_CURSOR_SIGNING_KEY=secrets.token_hex(32),ZEBRA_LIVE_REDIS_URL=f'redis://:{redispass}@live-full:6379/0',
        ZEBRA_LIVE_STREAM_KEY_PREFIX='zebra:erpnext-full:live',ZEBRA_LIVE_STREAM_MAX_LENGTH='4096',
        ZEBRA_S3_ENDPOINT='http://objects-full:9000',ZEBRA_S3_BUCKET='erpnext-full',ZEBRA_S3_ACCESS_KEY=access,ZEBRA_S3_SECRET_KEY=secret,
        ZEBRA_S3_REGION='us-east-1',ZEBRA_S3_KEY_PREFIX='erpnext-full',ZEBRA_RUNTIME_CLASS='gvisor',ZEBRA_RUNTIME_IMAGE=RUNTIME,
        ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA='true',ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB='256',ZEBRA_RUNTIME_DEFER_PROVISION='true',
        ZEBRA_WORKSPACE_VOLUME_ROOT='/var/lib/zebra/erpnext-full-workspaces',ZEBRA_WORKSPACE_VOLUME_LAYOUT='per-workspace',
        ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED='true',ZEBRA_HOST_EXECUTION_AUTHORITY_TOOL='erpnext.authority',
        ZEBRA_HOST_TOOL_SHARED_SECRET=current['zebra_agent']['host_secret'],ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES=HOST,
        ZEBRA_HOST_TOOL_WORKLOAD_IDENTITY='erpnext-worker',SSL_CERT_FILE='/run/full-public/ca-bundle.crt',REQUESTS_CA_BUNDLE='/run/full-public/ca-bundle.crt',
        ZEBRA_WEB_SEARCH_ENDPOINT=f'https://{SEARCH}:18546/search',ZEBRA_WEB_SEARCH_PRIVATE_BACKEND='true',
        ZEBRA_MCP_SECRET_ROOT='/run/mcp',ZEBRA_MCP_KEY_HANDLE='master',ZEBRA_MCP_KEY_VERSION='1',ZEBRA_CLIENT_INTEGRATION_ENABLED='true')
    for flag in ['EXTENSIONS_READ','EXTENSIONS_MANAGE','EXTENSION_TURN_ADMISSION','EXTENSION_WORKER','SKILL_WORKER','SKILLS_PUBLISH','MCP_CREDENTIALS','MCP_REFRESH','MCP_WORKER']:
        values['ZEBRA_CLOUD_'+flag+'_ENABLED']='true'
    private(ROOT/'api.env',''.join(k+'='+v+'\n' for k,v in values.items()))
    values.update(DOCKER_HOST='unix:///var/run/docker.sock',ZEBRA_RUNTIME_ENGINE='docker',
        ZEBRA_ERPNEXT_ALLOCATOR_SOCKET='/run/allocator/allocator.sock',ZEBRA_ERPNEXT_ALLOCATOR_KEY_FILE='/run/allocator/key')
    private(ROOT/'worker.env',''.join(k+'='+v+'\n' for k,v in values.items()))
    schedule_secret=secrets.token_urlsafe(48)
    schedule={**values,'ZEBRA_SCHEDULER_ID':'erpnext-full-scheduler','ZEBRA_SCHEDULER_GRANT_EXCHANGE_PROTOCOL':'generic',
        'ZEBRA_SCHEDULER_GRANT_ISSUER':current['zebra_agent']['issuer'],'ZEBRA_SCHEDULER_GRANT_AUDIENCE':'zebra',
        'ZEBRA_SCHEDULER_GRANT_JWKS_URI':f'https://{HOST}/api/method/zebra_erpnext.gateway.jwks',
        'ZEBRA_SCHEDULER_ALLOWED_ORIGINS':current['zebra_agent']['origin'],
        'ZEBRA_SCHEDULER_GRANT_EXCHANGE_URL':f'https://{HOST}/api/method/zebra_erpnext.api.schedule_exchange',
        'ZEBRA_SCHEDULER_WORKLOAD_IDENTITY':'erpnext-scheduler-full','ZEBRA_SCHEDULER_WORKLOAD_SHARED_SECRET':schedule_secret}
    private(ROOT/'scheduler.env',''.join(k+'='+v+'\n' for k,v in schedule.items()))
    full=dict(base_url=f'https://{AGENT}',enabled=True,acceptance_passed=False,namespace_id='erpnext-full',
        issuer=current['zebra_agent']['issuer'],origin=current['zebra_agent']['origin'],ca_file='/run/full-public/ca-bundle.crt',
        capability_profiles=['business','research','analysis'],capabilities={k:True for k in ['attachments','web','extensions','knowledge','schedules']},
        schedule_workload_secret=schedule_secret,frontend_profile_revision=2)
    private(ROOT/'full-settings.json',json.dumps(full))
    caddy=f'''{{\n admin off\n}}\nhttps://{HOST} {{\n tls /tls/runtime.crt /tls/runtime.key\n @manifest path /manifest\n handle @manifest {{\n rewrite * /api/method/zebra_erpnext.gateway.manifest\n reverse_proxy erpnext-backend-1:8000 {{\n header_up X-Frappe-Site-Name 192.168.110.42\n }}\n }}\n @invoke path /tools/*/invoke\n handle @invoke {{\n rewrite * /api/method/zebra_erpnext.gateway.invoke\n reverse_proxy erpnext-backend-1:8000 {{\n header_up X-Frappe-Site-Name 192.168.110.42\n }}\n }}\n handle {{\n reverse_proxy erpnext-backend-1:8000 {{\n header_up X-Frappe-Site-Name 192.168.110.42\n }}\n }}\n}}\nhttps://{AGENT} {{\n tls /tls/runtime.crt /tls/runtime.key\n reverse_proxy api-full:8000\n}}\n'''
    (ROOT/'Caddyfile').write_text(caddy)
    (ROOT/'search-Caddyfile').write_text(f'''{{\n admin off\n auto_https disable_redirects\n}}\nhttps://{SEARCH}:18546 {{\n bind 192.168.160.1\n tls /tls/runtime.crt /tls/runtime.key\n @search {{\n method GET\n path /search /healthz\n }}\n handle @search {{\n reverse_proxy 127.0.0.1:18446\n }}\n handle {{\n respond 404\n }}\n log {{\n output discard\n }}\n}}\n''')
    common={'security_opt':['no-new-privileges:true']}
    public_mount=str(public)+':/run/full-public:ro';mcp_mount=str(mcp)+':/run/mcp:ro'
    containers={
        'postgres':service(PG,env_file=[str(ROOT/'postgres.env')],environment={'POSTGRES_USER':'erpnext_full','POSTGRES_DB':DB},
            volumes=['/data/erpnext-agent-full/postgres:/var/lib/postgresql/data'],networks={NETWORK:{'aliases':['native-full-db']}}),
        'redis':service(REDIS,command=['redis-server','/run/redis.conf'],volumes=['/data/erpnext-agent-full/redis:/data',str(ROOT/'redis.conf')+':/run/redis.conf:ro'],networks={NETWORK:{'aliases':['live-full']}}),
        'objects':service(OBJECTS,user='1000:1000',env_file=[str(ROOT/'objects.env')],command=['server','/data'],volumes=['/data/erpnext-agent-full/objects:/data'],networks={NETWORK:{'aliases':['objects-full']}}),
        'tls':service(CADDY,volumes=[str(tls)+':/tls:ro',str(ROOT/'Caddyfile')+':/etc/caddy/Caddyfile:ro'],networks={NETWORK:{'aliases':[HOST,AGENT]},'erpnext_default':{'aliases':[HOST,AGENT]}}),
        'search-tls':service(CADDY,network_mode='host',volumes=[str(tls)+':/tls:ro',str(ROOT/'search-Caddyfile')+':/etc/caddy/Caddyfile:ro']),
        'api':service(NATIVE,entrypoint=['python','-m','zebra_agent_api.server'],env_file=[str(ROOT/'api.env')],read_only=True,tmpfs=['/tmp:rw,size=32m'],cap_drop=['ALL'],
            volumes=[public_mount,mcp_mount],networks={NETWORK:{'aliases':['api-full']}},**common),
        'worker':service(worker,entrypoint=['python','/deployment/full_worker.py'],env_file=[str(ROOT/'worker.env')],user='65532:65532',group_add=[str(Path('/var/run/docker.sock').stat().st_gid)],cap_drop=['ALL'],
            extra_hosts=[SEARCH+':192.168.160.1'],volumes=[public_mount,mcp_mount,'/var/run/docker.sock:/var/run/docker.sock',
                '/run/zebra-erp-full:/run/allocator:ro',{'type':'bind','source':'/var/lib/zebra/erpnext-full-workspaces','target':'/var/lib/zebra/erpnext-full-workspaces','bind':{'propagation':'rshared'}}],
            networks=[NETWORK,'zebra-dependencies'],**common),
        'scheduler':service(NATIVE,entrypoint=['python','-m','zebra_agent_scheduler.main'],env_file=[str(ROOT/'scheduler.env')],volumes=[public_mount,mcp_mount],networks=[NETWORK],**common)}
    private(ROOT/'compose.json',json.dumps(dict(services=containers,networks={k:{'external':True} for k in [NETWORK,'erpnext_default','zebra-dependencies']}),indent=2))
    compose('config','--quiet')
    compose('up','-d','postgres','redis','objects','tls','search-tls')
    for _ in range(60):
        r=os.system(f'docker exec {PREFIX}-postgres-1 pg_isready -h127.0.0.1 -Uerpnext_full -d{DB} -q >/dev/null 2>&1')
        if r==0:break
        time.sleep(.5)
    else:raise RuntimeError('new persistent database not ready')
    with (ROOT/'native105.current.dump').open('rb') as source:
        run('docker','exec','-i',PREFIX+'-postgres-1','pg_restore','--single-transaction','--no-owner','--no-acl','-U','erpnext_full','-d',DB,stdin=source,stdout=subprocess.DEVNULL)
    migration="from agent_storage.postgres.migration_runner import apply_postgres_migrations;import os;apply_postgres_migrations(os.environ['ZEBRA_DATABASE_URL']);print('fresh production clone migrated115')"
    run('docker','run','--rm','--network',NETWORK,'--env-file',str(ROOT/'api.env'),'--entrypoint','python',NATIVE,'-c',migration)
    private(ROOT/'prepared.json',json.dumps(dict(api_image=NATIVE,worker_image=worker,erp_image=ERP,source_backup='native105.current.dump',namespace='erpnext-full',schema=115,host_activated=False,worker_started=False,scheduler_started=False)))
    print(json.dumps(dict(stage='durable_production_dependencies_prepared',api_image=NATIVE,worker_image=worker,host_activated=False,model_calls=0,search_calls=0)))


if __name__=='__main__':main()
