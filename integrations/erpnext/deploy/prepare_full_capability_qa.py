"""Dedicated source-pinned QA stack. Never alter production configuration or start a Worker."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import time

ROOT=Path('/opt/erpnext/zebra-agent/full-capability-qa-20261028-2')
PREFIX='erp-full-qa-20261028-2'
NETWORK='erpnext-full-qa-proof'
API_BASE='sha256:6e4b2cdfa32b216800d5b8ff100565eb4b7664347af781a17d3a961bb3edcba2'
ERP_BASE='sha256:7c6b26efc787'
RUNTIME='swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python@sha256:52331dac368d5bcf1c00d30a782753d28bb7286a12b7bb629f388cec4cfd6fb2'
DB='erp_agent_capability_qa_20261028'


def run(*argv,**kwargs):
    return subprocess.run(list(argv),check=True,**kwargs)


def capture(*argv):
    return subprocess.check_output(list(argv),text=True)


def image(value):
    return json.loads(capture('docker','image','inspect',value))[0]['Id']


def wait(name,command):
    for _ in range(120):
        if subprocess.run(['docker','exec',name,*command],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:return
        time.sleep(.5)
    raise RuntimeError('QA dependency not ready: '+name)


def write(path,value):
    path.write_text(value);path.chmod(0o600)


def main():
    os.environ['DOCKER_BUILDKIT']='0'
    if not ROOT.is_dir() or (ROOT/'inventory.json').exists():raise ValueError('fresh pre-created isolated evidence root required')
    if NETWORK in capture('docker','network','ls','--format','{{.Name}}').splitlines():raise ValueError('QA network already exists; inspect retained evidence')
    names=capture('docker','ps','-a','--format','{{.Names}}').splitlines()
    if any(n.startswith(PREFIX) for n in names):raise ValueError('QA stack already exists')
    before={}
    for name in ['erpnext-agent-api-1','erpnext-agent-chat-worker-1','erpnext-backend-1','zebra-web-search-searxng-1','zebra-yahoo-egress']:
        item=json.loads(capture('docker','inspect',name))[0]
        before[name]=dict(id=item['Id'],image=item['Image'],started=item['State']['StartedAt'],restarts=item['RestartCount'])
    write(ROOT/'before.json',json.dumps(before,indent=2))
    for archive,folder in [('native.tar.gz','native'),('erp.tar.gz','erp')]:
        target=ROOT/folder;target.mkdir()
        with tarfile.open(ROOT/archive) as bundle:bundle.extractall(target,filter='data')
    source=ROOT/'native'
    pythonpath=':'.join('/candidate/'+str(p.relative_to(source)) for p in sorted(source.glob('packages/*/src'))+sorted(source.glob('apps/*/src')))
    native_docker=f'FROM {image(API_BASE)}\nCOPY native /candidate\nCOPY erp/deploy/runtime /deployment\nENV PYTHONPATH={pythonpath}:/deployment\nENV PYTHONDONTWRITEBYTECODE=1\n'
    (ROOT/'Dockerfile.native').write_text(native_docker)
    with (ROOT/'build-native.log').open('x') as log:
        run('docker','build','--network=none','--pull=false','-f',str(ROOT/'Dockerfile.native'),'-t',PREFIX+'-native',str(ROOT),stdout=log,stderr=subprocess.STDOUT)
    (ROOT/'Dockerfile.erp').write_text(f'FROM {image(ERP_BASE)}\nCOPY --chown=1000:1000 erp/zebra_erpnext /home/frappe/frappe-bench/apps/zebra_erpnext/zebra_erpnext\n')
    with (ROOT/'build-erp.log').open('x') as log:
        run('docker','build','--network=none','--pull=false','-f',str(ROOT/'Dockerfile.erp'),'-t',PREFIX+'-erp',str(ROOT),stdout=log,stderr=subprocess.STDOUT)
    start_services()


def start_services():
    if NETWORK in capture('docker','network','ls','--format','{{.Name}}').splitlines():
        raise ValueError('QA network already exists; do not repeat setup')
    native_image=image(PREFIX+'-native');erp_image=image(PREFIX+'-erp')
    run('docker','network','create','--internal',NETWORK,stdout=subprocess.DEVNULL)
    common=['--network',NETWORK,'--security-opt','no-new-privileges']
    run('docker','run','-d','--name',PREFIX+'-pg',*common,'--network-alias','native-db',
        '--tmpfs','/var/lib/postgresql/data:rw,size=1g','-e','POSTGRES_HOST_AUTH_METHOD=trust',
        '-e','POSTGRES_USER=erpnext_agent','-e','POSTGRES_DB='+DB,image('sha256:5d004e058f52'),stdout=subprocess.DEVNULL)
    wait(PREFIX+'-pg',['pg_isready','-U','erpnext_agent'])
    run('docker','cp','/opt/erpnext/zebra-agent/capability-upgrade-20261028-1/native114-isolated.dump',PREFIX+'-pg:/tmp/original.dump')
    run('docker','exec',PREFIX+'-pg','pg_restore','--single-transaction','--no-owner','--no-acl','-U','erpnext_agent','-d',DB,'/tmp/original.dump',stdout=subprocess.DEVNULL)
    maria_password=secrets.token_urlsafe(32)
    write(ROOT/'maria.env','MARIADB_ROOT_PASSWORD='+maria_password+'\n')
    run('docker','run','-d','--name',PREFIX+'-db',*common,'--network-alias','host-db',
        '--tmpfs','/var/lib/mysql:rw,size=2g','--env-file',str(ROOT/'maria.env'),image('sha256:f16d7a344413'),stdout=subprocess.DEVNULL)
    wait(PREFIX+'-db',['sh','-c','mariadb-admin --protocol=tcp -h127.0.0.1 ping -uroot -p"$MARIADB_ROOT_PASSWORD" --silent'])
    production_site=json.loads(capture('docker','exec','erpnext-backend-1','cat','/home/frappe/frappe-bench/sites/192.168.110.42/site_config.json'))
    # Current database is read under the native transactional dump, without touching a business record.
    with (ROOT/'erp-original.sql').open('xb') as output:
        run('docker','exec','erpnext-db-1','sh','-c','exec mariadb-dump --single-transaction --skip-lock-tables --databases "$1" -uroot -p"$MYSQL_ROOT_PASSWORD"','--',production_site['db_name'],stdout=output,stderr=subprocess.DEVNULL)
    (ROOT/'erp-original.sql').chmod(0o600)
    with (ROOT/'erp-original.sql').open('rb') as data:
        run('docker','exec','-i',PREFIX+'-db','sh','-c','exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD"',stdin=data,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    finish_host(maria_password,production_site,native_image,erp_image,common)


def finish_host(maria_password,production_site,native_image,erp_image,common):
    run('docker','run','-d','--name',PREFIX+'-redis',*common,'--network-alias','host-redis',image('sha256:7033ad495c19'),stdout=subprocess.DEVNULL)
    sites=PREFIX+'-sites';run('docker','volume','create',sites,stdout=subprocess.DEVNULL)
    copy="import shutil,os;shutil.copytree('/original','/target',dirs_exist_ok=True,symlinks=True);[(os.lchown(d,1000,1000),[os.lchown(os.path.join(d,n),1000,1000) for n in dirs+files]) for d,dirs,files in os.walk('/target',followlinks=False)]"
    run('docker','run','--rm','--network','none','--user','0','-v','erpnext_sites:/original:ro','-v',sites+':/target','--entrypoint','python',erp_image,'-c',copy,stdout=subprocess.DEVNULL)
    tls=ROOT/'tls';tls.mkdir(mode=0o755)
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(tls/'server.key'),'-out',str(tls/'server.crt'),'-days','3','-subj','/CN=erpnext-full-qa.zebra.local','-addext','subjectAltName=DNS:erpnext-full-qa.zebra.local,DNS:agent-full-qa.zebra.local,IP:127.0.0.1',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for name in ['server.key','server.crt']:(tls/name).chmod(0o644 if name.endswith('crt') else 0o600)
    run('openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(tls/'signing.key'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (tls/'signing.key').chmod(0o644) # Isolated ephemeral QA-only key, not a production credential.
    config=dict(production_site)
    config.update(db_host='host-db',db_user='root',db_password=maria_password,redis_cache='redis://host-redis:6379/0',redis_queue='redis://host-redis:6379/1',pause_scheduler=1)
    common_agent=dict(enabled=True,base_url='https://agent-full-qa.zebra.local',issuer='https://erpnext-full-qa.zebra.local',origin='https://127.0.0.1:18544',signing_key='/qa/signing.key',ca_file='/qa/server.crt',host_secret=secrets.token_urlsafe(48),admission_paused=False,chat_readonly_enabled=True)
    full=dict(base_url=common_agent['base_url'],namespace_id='erpnext-full',enabled=True,acceptance_passed=True,
        capability_profiles=['business','research','analysis'],capabilities={k:True for k in ['attachments','web','extensions','knowledge','schedules']},
        frontend_profile_revision=2,schedule_workload_secret=secrets.token_urlsafe(48))
    common_agent['runtimes']={'cloud114':full};config['zebra_agent']=common_agent
    write(ROOT/'site.json',json.dumps(config))
    modify="import json,pathlib,os;p=pathlib.Path('/target');s=p/'192.168.110.42';s.rename(p/'capability-qa.local');(p/'capability-qa.local/site_config.json').write_text(pathlib.Path('/config.json').read_text());(p/'common_site_config.json').write_text(json.dumps(dict(redis_cache='redis://host-redis:6379/0',redis_queue='redis://host-redis:6379/1',socketio_port=9000,default_site='capability-qa.local',serve_default_site=True)));os.chown(p/'capability-qa.local/site_config.json',1000,1000)"
    run('docker','run','--rm','--network','none','--user','0','-v',sites+':/target','-v',str(ROOT/'site.json')+':/config.json:ro','--entrypoint','python',erp_image,'-c',modify)
    s3_access='qa'+secrets.token_hex(12);s3_secret=secrets.token_urlsafe(40)
    write(ROOT/'s3.env',f'MINIO_ROOT_USER={s3_access}\nMINIO_ROOT_PASSWORD={s3_secret}\n')
    run('docker','run','-d','--name',PREFIX+'-s3',*common,'--network-alias','objects','--tmpfs','/data:rw,size=512m','--env-file',str(ROOT/'s3.env'),image('sha256:a1ea29fa2835'),'server','/data',stdout=subprocess.DEVNULL)
    # No provider credential is copied. No Worker or scheduler is started.
    env=dict(ZEBRA_PROFILE='cloud',ZEBRA_DEPLOYMENT='cloud',ZEBRA_STORAGE_AUTHORITY='postgresql',ZEBRA_DATABASE_URL='postgresql://erpnext_agent@native-db:5432/'+DB,ZEBRA_DEPLOYMENT_NAMESPACE='erpnext-full',
        ZEBRA_STREAM_V2_NEW_ADMISSION_ENABLED='true',ZEBRA_STREAM_V2_CURSOR_SIGNING_KEY=secrets.token_hex(32),ZEBRA_LIVE_REDIS_URL='redis://host-redis:6379/3',ZEBRA_MEMORY_CURSOR_SIGNING_KEY=secrets.token_hex(32),ZEBRA_AUTHORITY_ISSUER=common_agent['issuer'],ZEBRA_HISTORY_SCOPE_NAMESPACE='erpnext-full',ZEBRA_CONTINUATION_SCOPE_NAMESPACE='erpnext-full',
        ZEBRA_S3_ENDPOINT='http://objects:9000',ZEBRA_S3_BUCKET='erp-full-qa',ZEBRA_S3_ACCESS_KEY=s3_access,ZEBRA_S3_SECRET_KEY=s3_secret,ZEBRA_RUNTIME_CLASS='gvisor',ZEBRA_RUNTIME_IMAGE=RUNTIME,
        ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA='true',ZEBRA_RUNTIME_WORKSPACE_QUOTA_MB='256',ZEBRA_WORKSPACE_VOLUME_ROOT='/var/lib/zebra/erpnext-full-qa-workspaces',ZEBRA_WORKSPACE_VOLUME_LAYOUT='per-workspace',ZEBRA_HOST_EXECUTION_AUTHORITY_ENABLED='true',
        ZEBRA_HOST_EXECUTION_AUTHORITY_TOOL='erpnext.authority',ZEBRA_HOST_TOOL_SHARED_SECRET=common_agent['host_secret'],ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES='erpnext-full-qa.zebra.local',SSL_CERT_FILE='/qa/server.crt',ZEBRA_RUNTIME_DEFER_PROVISION='true')
    for flag in ['EXTENSIONS_READ','EXTENSIONS_MANAGE','EXTENSION_TURN_ADMISSION','EXTENSION_WORKER','SKILL_WORKER','SKILLS_PUBLISH','MCP_CREDENTIALS','MCP_REFRESH','MCP_WORKER']:env['ZEBRA_CLOUD_'+flag+'_ENABLED']='true'
    write(ROOT/'native.env',''.join(k+'='+v+'\n' for k,v in env.items()))
    run('docker','run','-d','--name',PREFIX+'-host',*common,'--network-alias','host-backend','-v',sites+':/home/frappe/frappe-bench/sites','-v',str(tls)+':/qa:ro',erp_image,stdout=subprocess.DEVNULL)
    with (ROOT/'host-migration.log').open('x') as log:
        run('docker','exec',PREFIX+'-host','bench','--site','capability-qa.local','execute','zebra_erpnext.install.setup',stdout=log,stderr=subprocess.STDOUT)
    write(ROOT/'inventory.json',json.dumps(dict(native_image=native_image,erp_image=erp_image,network=NETWORK,prefix=PREFIX,sites=sites,worker_started=False,scheduler_started=False,model_calls=0,search_calls=0),indent=2))
    print(json.dumps(dict(stage='isolated_services_prepared',prefix=PREFIX,worker_started=False,production_changed=False)))


if __name__=='__main__':main()
