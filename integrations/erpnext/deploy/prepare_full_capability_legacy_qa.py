"""Keep old conversation authority on a separate QA API; never rebind original Tasks."""
import json
import subprocess
from pathlib import Path
from prepare_full_capability_qa import ROOT,PREFIX,NETWORK


def main():
    state=json.loads((ROOT/'inventory.json').read_text())
    if state['prefix']!=PREFIX or state['worker_started'] is not False:raise ValueError('idle QA only')
    identity=json.loads((ROOT/'legacy-identity.json').read_text())
    if identity['issuer']!='https://erpnext.zebra.local':raise ValueError('original issuer drift')
    site=json.loads((ROOT/'site.json').read_text());base=site['zebra_agent'];full=base['runtimes']['cloud114']
    full.update(issuer=base['issuer'],origin=base['origin'])
    base.update(base_url='https://agent-full-qa.zebra.local:444',issuer=identity['issuer'],origin=identity['origin'],
        chat_readonly_enabled=True,production_plan_proposals_enabled=True)
    (ROOT/'site.json').write_text(json.dumps(site))
    values={line.split('=',1)[0]:line.split('=',1)[1] for line in (ROOT/'api.env').read_text().splitlines() if '=' in line}
    values.update(ZEBRA_DEPLOYMENT_NAMESPACE='erpnext',ZEBRA_AUTHORITY_ISSUER=identity['issuer'],ZEBRA_HISTORY_SCOPE_NAMESPACE='erpnext',ZEBRA_CONTINUATION_SCOPE_NAMESPACE='erpnext')
    path=ROOT/'legacy-api.env';path.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));path.chmod(0o600)
    code="""from agent_storage import cloud_composition_from_environment
from agent_storage.postgres.host_auth import PostgresHostAuthorityStore,HostRegistryRecord
c=cloud_composition_from_environment()
assert c.deployment_namespace=='erpnext' and 'native-db' in c.dsn
PostgresHostAuthorityStore(c.dsn,deployment_namespace='erpnext').upsert_registry(HostRegistryRecord(host_app_id='erpnext',namespace_id='erpnext',issuer='https://erpnext.zebra.local',audience='zebra',jwks_uri='https://erpnext-full-qa.zebra.local/api/method/zebra_erpnext.gateway.jwks',allowed_origins=('https://192.168.110.42:18443',),algorithms=('RS256',),policy_version='erpnext-v1'))
print('QA legacy public verifier seeded; original Task bindings unchanged')"""
    subprocess.run(['docker','run','--rm','--network',NETWORK,'--env-file',str(path),'-v',str(ROOT/'tls')+':/qa:ro',
        '--entrypoint','python',state['native_image'],'-c',code],check=True)
    subprocess.run(['docker','run','-d','--name',PREFIX+'-legacy-api','--network',NETWORK,'--network-alias','native-legacy-api',
        '--env-file',str(path),'-v',str(ROOT/'tls')+':/qa:ro','-v',str(ROOT/'mcp')+':/mcp:ro',
        '--entrypoint','python',state['native_image'],'-m','zebra_agent_api.server'],check=True,stdout=subprocess.DEVNULL)
    config=ROOT/'Caddyfile';content=config.read_text()
    content+='\nhttps://agent-full-qa.zebra.local:444 {\n tls /qa/server.crt /qa/server.key\n reverse_proxy native-legacy-api:8000\n}\n'
    config.write_text(content)
    subprocess.run(['docker','exec',PREFIX+'-tls','caddy','reload','--config','/etc/caddy/Caddyfile'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['docker','cp',str(ROOT/'site.json'),PREFIX+'-host:/home/frappe/frappe-bench/sites/capability-qa.local/site_config.json'],check=True)
    subprocess.run(['docker','exec','--user','0',PREFIX+'-host','chown','1000:1000','/home/frappe/frappe-bench/sites/capability-qa.local/site_config.json'],check=True)
    subprocess.run(['docker','exec',PREFIX+'-host','bench','--site','capability-qa.local','clear-cache'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','restart',PREFIX+'-host'],check=True,stdout=subprocess.DEVNULL)
    print(json.dumps(dict(stage='legacy_isolated_route_ready',original_bindings_unchanged=True,production_changed=False,model_calls=0,search_calls=0)))


if __name__=='__main__':main()
