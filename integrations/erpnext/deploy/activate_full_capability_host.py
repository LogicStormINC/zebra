"""Replace only ERP backend/frontend with the accepted image; new release stays gated."""
import json
from activate_full_capability import *


def main():
    require_no_active()
    state=json.loads((ROOT/'prepared.json').read_text())
    if state['host_activated']:raise ValueError('Host already activated; inspect original receipt')
    profile=json.loads((ROOT/'frontend-profile.json').read_text())
    full=json.loads((ROOT/'full-settings.json').read_text());full['frontend_profile']=profile
    private(ROOT/'full-settings.json',json.dumps(full))
    before=ROOT/'erpnext-override.before.json'
    original=Path('/opt/erpnext/zebra-agent/erpnext-override.json')
    if before.exists():raise ValueError('Host override backup already exists')
    private(before,original.read_text())
    # Bind the new public trust only. Original signing material remains unchanged.
    override=json.loads(original.read_text())
    override['services']['backend']['image']=ERP;override['services']['frontend']['image']=ERP
    mounts=override['services']['backend'].setdefault('volumes',[])
    mounts.append(str(ROOT/'public')+':/run/full-public:ro')
    # Preserve current process settings; Compose retains existing log volumes.
    for name,role in [('erpnext-backend-1','backend'),('erpnext-frontend-1','frontend')]:
        actual=json.loads((ROOT/(name+'.inspect.json')).read_text())
        keys=('GUNICORN_',) if role=='backend' else ('SOCKETIO','CLIENT_MAX_BODY_SIZE','UPSTREAM_','FRAPPE_SITE_NAME_HEADER','NGINX_','BACKEND','PROXY_READ_TIMEOUT')
        override['services'][role]['environment']={v.split('=',1)[0]:v.split('=',1)[1] for v in actual['Config']['Env'] if v.startswith(keys)}
    private(ROOT/'erpnext-override.after.json',json.dumps(override,indent=2))
    run('docker','cp',str(ROOT/'full-settings.json'),'erpnext-backend-1:/tmp/full-capability-settings.json')
    run('docker','exec','--user','0','erpnext-backend-1','chown','1000:1000','/tmp/full-capability-settings.json')
    update="import json,pathlib;p=pathlib.Path('/home/frappe/frappe-bench/sites/192.168.110.42/site_config.json');s=json.loads(p.read_text());c=json.loads(pathlib.Path('/tmp/full-capability-settings.json').read_text());assert c['acceptance_passed'] is False;s['zebra_agent'].setdefault('runtimes',{})['cloud114']=c;p.write_text(json.dumps(s,indent=2));print('new runtime configured; new-conversation gate remains closed')"
    run('docker','exec','erpnext-backend-1','python','-c',update)
    private(original,json.dumps(override,indent=2))
    paths=['/opt/erpnext/frappe_docker/compose.yaml','/opt/erpnext/frappe_docker/overrides/compose.mariadb.yaml',
        '/opt/erpnext/frappe_docker/overrides/compose.redis.yaml','/opt/erpnext/frappe_docker/overrides/compose.noproxy.yaml',str(original)]
    command=['docker','compose','--env-file','/opt/erpnext/.env','-p','erpnext','--project-directory','/opt/erpnext/frappe_docker']
    for path in paths:command+=['-f',path]
    run(*command,'config','--quiet')
    require_no_active()
    run(*command,'up','-d','--no-deps','--pull','never','backend','frontend')
    with (ROOT/'host-schema-setup.log').open('x') as log:
        run('docker','exec','erpnext-backend-1','bench','--site','192.168.110.42','execute','zebra_erpnext.install.setup',stdout=log,stderr=log)
    run('docker','exec','erpnext-backend-1','bench','--site','192.168.110.42','clear-cache',stdout=subprocess.DEVNULL)
    state['host_activated']=True;private(ROOT/'prepared.json',json.dumps(state))
    print(json.dumps(dict(stage='accepted_erp_host_activated',image=ERP,new_conversation_gate=False,legacy_runtime_unchanged=True)))


if __name__=='__main__':main()
