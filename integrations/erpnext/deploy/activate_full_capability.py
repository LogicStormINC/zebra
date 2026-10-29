"""Fixed production release coordinates and narrow operator commands."""
import json
from pathlib import Path
import subprocess

ROOT=Path('/opt/erpnext/zebra-agent/full-runtime-20261029-1')
BACKUP=Path('/opt/erpnext/zebra-agent/full-capability-release-ready-20261029-1')
PREFIX='erpnext-full'
NETWORK='erpnext-full-proof'
DB='erpnext_full_runtime'
NATIVE='sha256:9a09d2d50d5ae7f9fd0cb3167427fa25101b055f2e2c315d6ffe642d875526f2'
ERP='sha256:2d16a18f2af4ba76c5d3698db8c2330265b12eac8deffbffa5284e43aed53588'
TOOLS='sha256:e511e71805ff353f95dd65236e90ea225281ab903108b5e0becc0307f4b1f9af'
RUNTIME='swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python@sha256:52331dac368d5bcf1c00d30a782753d28bb7286a12b7bb629f388cec4cfd6fb2'
HOST='erpnext-full-host.zebra.local'
AGENT='erpnext-full-agent.zebra.local'
SEARCH='search-erpnext-full.zebra.local'


def run(*args,**kwargs):return subprocess.run(args,check=True,**kwargs)
def capture(*args):return subprocess.check_output(args,text=True)
def private(path,value):
    path.write_text(value);path.chmod(0o600)
def env(path):return dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line)
def compose(*args):return run('docker','compose','-p',PREFIX,'-f',str(ROOT/'compose.json'),*args)
def root(*args,**kwargs):
    # Existing operator pattern: fixed owned release commands in host mount namespace.
    code="import os,sys;r=os.open('/proc/1/root',os.O_DIRECTORY);n=os.open('/proc/1/ns/mnt',os.O_RDONLY);os.setns(n,0);os.fchdir(r);os.chroot('.');os.chdir('/');os.execv('/usr/bin/'+sys.argv[1],sys.argv[1:])"
    return run('docker','run','--rm','--privileged','--pid=host','--network','none','--user','0',
        '--entrypoint','python',NATIVE,'-c',code,*args,**kwargs)


def require_no_active():
    count=capture('docker','exec','erpnext-agent-postgres-1','psql','-U','erpnext_agent','-d','erpnext_agent','-Atc',
        "SELECT count(*) FROM session_projections WHERE status='running';").strip()
    if count!='0':raise ValueError('active legacy Run exists; do not replace Host')


def service(image,**values):
    return dict(image=image,restart='unless-stopped',logging={'driver':'json-file','options':{'max-size':'10m','max-file':'3'}},**values)
