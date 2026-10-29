"""Operator-only isolated clone preparation; no production settings or restart."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import time

ROOT = Path('/opt/erpnext/zebra-agent/capability-upgrade-20261028-1')
CLONE = 'erp-agent-capability-qa-pg-20261028-1'
DATABASE = 'erp_agent_capability_qa_20261028'
PG_IMAGE = 'sha256:5d004e058f52'
API_IMAGE = 'sha256:6e4b2cdfa32b216800d5b8ff100565eb4b7664347af781a17d3a961bb3edcba2'


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, **kwargs)


def main():
    archive = ROOT / 'cloud-agent-8b4da99f.tar.gz'
    if not (ROOT / 'native105.dump').is_file() or not archive.is_file():
        raise ValueError('Protected source freeze and original backup required')
    if (ROOT / 'source').exists():
        raise ValueError('Refusing to replace a previous candidate')
    # Resolve cached identities only. Never pull an image or inherit production env.
    pg = json.loads(subprocess.check_output(['docker', 'image', 'inspect', PG_IMAGE]))[0]['Id']
    api = json.loads(subprocess.check_output(['docker', 'image', 'inspect', API_IMAGE]))[0]['Id']
    names = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True)
    if CLONE in names.splitlines():
        raise ValueError('Owned clone already exists; inspect it instead of retrying')
    source = ROOT / 'source'
    source.mkdir(mode=0o755)
    with tarfile.open(archive) as bundle:
        bundle.extractall(source, filter='data')
    run('docker', 'run', '-d', '--name', CLONE, '--network', 'none',
        '--memory', '2g', '--cpus', '2', '--security-opt', 'no-new-privileges',
        '--tmpfs', '/var/lib/postgresql/data:rw,size=1g',
        '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_USER=erpnext_agent',
        '-e', 'POSTGRES_DB=' + DATABASE, pg, stdout=subprocess.DEVNULL)
    for _ in range(100):
        probe = subprocess.run(['docker', 'exec', CLONE, 'pg_isready', '-h', '127.0.0.1', '-U', 'erpnext_agent'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('Isolated PostgreSQL did not start; clone retained')
    run('docker', 'cp', str(ROOT / 'native105.dump'), CLONE + ':/tmp/original.dump')
    run('docker', 'exec', CLONE, 'pg_restore', '--single-transaction', '--no-owner', '--no-acl',
        '-U', 'erpnext_agent', '-d', DATABASE, '/tmp/original.dump')
    migrate(source, pg, api)



def migrate(source, pg, api):
    archive = ROOT / 'cloud-agent-8b4da99f.tar.gz'
    paths = sorted(source.glob('packages/*/src')) + sorted(source.glob('apps/*/src'))
    pythonpath = ':'.join('/candidate/' + str(path.relative_to(source)) for path in paths)
    manifest = {'source_commit': '8b4da99f85d656531575eca1980d5a0bfb9197d2',
        'source_archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'backup_sha256': hashlib.sha256((ROOT / 'native105.dump').read_bytes()).hexdigest(),
        'postgres_image': pg, 'python_dependency_base': api,
        'clone_container': CLONE, 'database': DATABASE, 'ports': [],
        'production_settings_copied': False, 'worker_started': False}
    (ROOT / 'candidate.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with (ROOT / 'migration.log').open('x') as log:
        run('docker', 'run', '--rm', '--name', 'erp-agent-capability-qa-migrate-20261028-1',
            '--network', 'container:' + CLONE, '--read-only', '--user',
            f'{ROOT.stat().st_uid}:{ROOT.stat().st_gid}',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '1g',
            '--tmpfs', '/tmp:rw,size=64m', '-v', str(source) + ':/candidate:ro',
            '-v', str(ROOT) + ':/evidence', '-e', 'PYTHONPATH=' + pythonpath,
            '-e', 'PYTHONDONTWRITEBYTECODE=1',
            '-e', 'ERP_CAPABILITY_QA_DSN=postgresql://erpnext_agent@127.0.0.1:5432/' + DATABASE,
            '-e', 'ERP_CAPABILITY_QA_OUTPUT=/evidence/migration.json',
            '--entrypoint', 'python', api, '/evidence/check_capability_upgrade.py',
            stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps({'stage': 'isolated_migration_complete', 'clone': CLONE,
        'evidence': str(ROOT / 'migration.json')}))


if __name__ == '__main__':
    main()
