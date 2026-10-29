"""Prepare only a new root-owned QA allocator; no production mount or worker loop."""
import json
from pathlib import Path
import secrets
import subprocess
from prepare_full_capability_qa import ROOT,PREFIX,NETWORK,capture,run as ordinary_run


def run(*argv,**kwargs):
    if argv[0]!='sudo':return ordinary_run(*argv,**kwargs)
    # Docker administration is already authorized; enter only for these fixed QA
    # mount/config commands, never accept a browser path or arbitrary operation.
    image=json.loads((ROOT/'inventory.json').read_text())['native_image']
    script="import os,sys;root=os.open('/proc/1/root',os.O_DIRECTORY);ns=os.open('/proc/1/ns/mnt',os.O_RDONLY);os.setns(ns,0);os.fchdir(root);os.chroot('.');os.chdir('/');os.execv('/usr/bin/'+sys.argv[1],sys.argv[1:])"
    return ordinary_run('docker','run','--rm','--privileged','--pid=host','--network','none',
        '--user','0','--entrypoint','python',image,'-c',script,*argv[1:],**kwargs)


def main():
    record=json.loads((ROOT/'inventory.json').read_text())
    if record['prefix']!=PREFIX:raise ValueError('dedicated QA stack required')
    operator=Path('/etc/zebra/erp-full-qa')
    volume=Path('/var/lib/zebra/erpnext-full-qa-workspaces')
    state=Path('/var/lib/zebra/erpnext-full-qa-volumes')
    socket=Path('/run/zebra-erp-full-qa')
    if any(p.exists() and (p.is_symlink() or any(p.iterdir()) or p.stat().st_uid!=0) for p in [operator,volume,state,socket]):
        raise ValueError('allocator paths contain state; inspect original data')
    for path in [operator,volume,state,socket]:run('sudo','install','-d','-o','0','-g','0','-m','755',str(path))
    run('sudo','chown','0:65532',str(socket));run('sudo','chmod','750',str(socket))
    run('sudo','mount','--bind',str(volume),str(volume))
    # Break inherited peers before sharing the dedicated subtree: otherwise a
    # shared host root can propagate the same child mount onto itself twice.
    run('sudo','mount','--make-private',str(volume))
    run('sudo','mount','--make-shared',str(volume))
    password=secrets.token_hex(32)
    # This role cannot mutate any native table, even if a proof implementation drifts.
    sql="CREATE ROLE full_qa_proof LOGIN PASSWORD '%s';GRANT CONNECT ON DATABASE erp_agent_capability_qa_20261028 TO full_qa_proof;GRANT USAGE ON SCHEMA public TO full_qa_proof;GRANT SELECT ON ALL TABLES IN SCHEMA public TO full_qa_proof;ALTER ROLE full_qa_proof SET default_transaction_read_only=on;ALTER ROLE full_qa_proof SET statement_timeout='5s';"%password
    run('docker','exec','-i',PREFIX+'-pg','psql','-U','erpnext_agent','-d','erp_agent_capability_qa_20261028','-v','ON_ERROR_STOP=1',input=sql.encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    host=json.loads((ROOT/'site.json').read_text())['zebra_agent']
    config=dict(generation='cloud114-qa',helper_image=record['native_image'],helper_network=NETWORK,
        helper_hostname='erpnext-full-qa.zebra.local',readonly_dsn='postgresql://full_qa_proof:'+password+'@native-db:5432/erp_agent_capability_qa_20261028',
        host_tool_shared_secret=host['host_secret'],host_ca_file=str(operator/'ca.crt'),worker_host_uid=65532,
        hmac_key_path=str(operator/'hmac.key'),socket_path=str(socket/'allocator.sock'))
    tmp=ROOT/'allocator-config.json';tmp.write_text(json.dumps(config));tmp.chmod(0o600)
    key=ROOT/'allocator.key';key.write_bytes(secrets.token_bytes(32));key.chmod(0o600)
    run('sudo','install','-o','0','-g','0','-m','600',str(tmp),str(operator/'config.json'))
    run('sudo','install','-o','0','-g','0','-m','600',str(key),str(operator/'hmac.key'))
    run('sudo','install','-o','0','-g','65532','-m','640',str(key),str(socket/'key'))
    run('sudo','install','-o','0','-g','0','-m','644',str(ROOT/'tls/server.crt'),str(operator/'ca.crt'))
    run('sudo','install','-o','0','-g','0','-m','644',str(ROOT/'private_workspace_operator.py'),str(operator/'private_workspace_operator.py'))
    run('sudo','systemd-run','--unit=zebra-erp-full-qa-20261028-v4','--property=Restart=no','--property=PrivateTmp=no',
        '/usr/bin/python3',str(operator/'private_workspace_operator.py'),str(operator/'config.json'),stdout=subprocess.DEVNULL)
    print(json.dumps(dict(stage='isolated_quota_operator_prepared',maximum_workspace_bytes=256*1024*1024,worker_started=False,model_calls=0,search_calls=0)))


if __name__=='__main__':main()
