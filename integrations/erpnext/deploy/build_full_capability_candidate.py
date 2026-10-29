"""Build immutable source-only candidates; migrate/recreate only the owned QA API/Host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from prepare_full_capability_qa import ROOT,PREFIX,NETWORK,API_BASE,ERP_BASE,image


def run(*args,**kwargs):return subprocess.run(args,check=True,**kwargs)


def main():
    state=json.loads((ROOT/'inventory.json').read_text())
    if state['prefix']!=PREFIX or state['worker_started'] is not False:raise ValueError('idle QA only')
    source=json.loads((ROOT/'final-source.json').read_text())
    target=ROOT/'build-final';target.mkdir()
    for name in ['native','erp']:
        archive=ROOT/(name+'-final.tar.gz')
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=source[name+'_archive_sha256']:raise ValueError('source archive changed')
        folder=target/name;folder.mkdir()
        with tarfile.open(archive) as bundle:bundle.extractall(folder,filter='data')
    pythonpath=':'.join('/candidate/'+str(p.relative_to(target/'native')) for p in sorted((target/'native').glob('packages/*/src'))+sorted((target/'native').glob('apps/*/src')))
    (target/'Dockerfile.native').write_text(f'FROM {image(API_BASE)}\nCOPY native /candidate\nCOPY erp/deploy/runtime /deployment\nENV PYTHONPATH={pythonpath}:/deployment\nENV PYTHONDONTWRITEBYTECODE=1\n')
    (target/'Dockerfile.erp').write_text(f'FROM {image(ERP_BASE)}\nCOPY --chown=1000:1000 erp/zebra_erpnext /home/frappe/frappe-bench/apps/zebra_erpnext/zebra_erpnext\n')
    os.environ['DOCKER_BUILDKIT']='0'
    for kind in ['native','erp']:
        with (ROOT/('build-final-'+kind+'.log')).open('x') as log:
            run('docker','build','--network=none','--pull=false','-f',str(target/('Dockerfile.'+kind)),'-t',PREFIX+'-final-'+kind,str(target),stdout=log,stderr=subprocess.STDOUT)
    native=image(PREFIX+'-final-native');erp=image(PREFIX+'-final-erp')
    code="from agent_storage.postgres.migration_runner import apply_postgres_migrations;import os;apply_postgres_migrations(os.environ['ZEBRA_DATABASE_URL']);print('isolated migration applied')"
    with (ROOT/'migration115.log').open('x') as log:
        run('docker','run','--rm','--network',NETWORK,'--env-file',str(ROOT/'api.env'),'--entrypoint','python',native,'-c',code,stdout=log,stderr=subprocess.STDOUT)
    for kind in ['api','host','frontend']:run('docker','rm','-f',PREFIX+'-'+kind,stdout=subprocess.DEVNULL)
    run('docker','run','-d','--name',PREFIX+'-api','--network',NETWORK,'--network-alias','native-api',
        '--add-host','search-full-qa.zebra.local:192.168.160.1','--env-file',str(ROOT/'api.env'),'-v',str(ROOT/'tls')+':/qa:ro',
        '-v',str(ROOT/'mcp')+':/mcp:ro','--entrypoint','python',native,'-m','zebra_agent_api.server',stdout=subprocess.DEVNULL)
    run('docker','network','connect','zebra-dependencies',PREFIX+'-api')
    run('docker','run','-d','--name',PREFIX+'-host','--network',NETWORK,'--network-alias','host-backend',
        '-v',state['sites']+':/home/frappe/frappe-bench/sites','-v',str(ROOT/'tls')+':/qa:ro',erp,stdout=subprocess.DEVNULL)
    run('docker','exec',PREFIX+'-host','bench','--site','capability-qa.local','clear-cache',stdout=subprocess.DEVNULL)
    run('docker','run','-d','--name',PREFIX+'-frontend','--network',NETWORK,'--network-alias','host-frontend',
        '-v',state['sites']+':/home/frappe/frappe-bench/sites','-e','BACKEND=host-backend:8000',
        '-e','SOCKETIO=host-backend:9000','-e','FRAPPE_SITE_NAME_HEADER=capability-qa.local',erp,'nginx-entrypoint.sh',stdout=subprocess.DEVNULL)
    state.update(pre_final_native_image=state['native_image'],native_image=native,pre_final_erp_image=state['erp_image'],erp_image=erp,final_source=source)
    (ROOT/'inventory.json').write_text(json.dumps(state,indent=2))
    print(json.dumps(dict(stage='immutable_candidate_built',native=native,erp=erp,production_changed=False,model_calls=0,search_calls=0)))


if __name__=='__main__':main()
