"""Read-only production backups and fixed candidate manifest; never activate a service."""
import json
from pathlib import Path
import subprocess
from datetime import datetime,timezone
from prepare_full_capability_qa import ROOT

DEST=Path('/opt/erpnext/zebra-agent/full-capability-release-ready-20261029-1')


def capture(*args):return subprocess.check_output(args)


def main():
    candidate=json.loads((ROOT/'inventory.json').read_text())
    if candidate.get('worker_started') is not False or not candidate.get('final_source'):
        raise ValueError('fixed unexecuted candidate required')
    DEST.mkdir(mode=0o700)
    images={}
    for name in ['erpnext-agent-api-1','erpnext-agent-chat-worker-1','erpnext-backend-1','erpnext-frontend-1','zebra-web-search-searxng-1','zebra-yahoo-egress']:
        row=json.loads(capture('docker','inspect',name))[0]
        images[name]=dict(id=row['Id'],image=row['Image'],started=row['State']['StartedAt'],restarts=row['RestartCount'])
    config=capture('docker','exec','erpnext-backend-1','cat','/home/frappe/frappe-bench/sites/192.168.110.42/site_config.json')
    site=json.loads(config)
    for name,value in [('site-config.before.json',config),('service-images.before.json',json.dumps(images,indent=2).encode())]:
        path=DEST/name;path.write_bytes(value);path.chmod(0o600)
    with (DEST/'native105-current.dump').open('xb') as out:
        subprocess.run(['docker','exec','erpnext-agent-postgres-1','pg_dump','-U','erpnext_agent','-d','erpnext_agent','-Fc'],check=True,stdout=out,stderr=subprocess.DEVNULL)
    with (DEST/'erp-current.sql').open('xb') as out:
        subprocess.run(['docker','exec','erpnext-db-1','sh','-c','exec mariadb-dump --single-transaction --skip-lock-tables --databases "$1" -uroot -p"$MYSQL_ROOT_PASSWORD"','--',site['db_name']],check=True,stdout=out,stderr=subprocess.DEVNULL)
    for name in ['native105-current.dump','erp-current.sql']:(DEST/name).chmod(0o600)
    manifest=dict(prepared_at=datetime.now(timezone.utc).isoformat(),native_image=candidate['native_image'],erp_image=candidate['erp_image'],
        source=candidate['final_source'],target_schema=115,production_activated=False,model_calls=0,search_calls=0,
        backup_bytes={n:(DEST/n).stat().st_size for n in ['native105-current.dump','erp-current.sql']},
        cutover_requirements=['never copy QA DB/bucket/user records into production','preserve old runtime/Run identities and ready work',
            'fresh target DB migration from current dump','separate full namespace/API/Worker/quota/S3/scheduler',
            'independent trusted TLS search endpoint; preserve original Search/MCP','enable new-conversation release last after signed no-model checks'])
    (DEST/'candidate.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps(dict(stage='production_backup_and_release_candidate_ready',backup_bytes=manifest['backup_bytes'],production_activated=False)))


if __name__=='__main__':main()
