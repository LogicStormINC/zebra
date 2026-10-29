"""Cached digest-pinned gVisor analysis on the isolated private filesystem only."""
import json
from pathlib import Path
import subprocess
import time
from prepare_full_capability_qa import ROOT,PREFIX,RUNTIME

CODE='''import csv,errno,json,os,socket
from pathlib import Path
p=Path('/workspace')
assert os.getuid()==65532 and {n for _,n in socket.if_nameindex()}=={'lo'}
assert int(next(s.split()[1] for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('CapEff:')),16)==0
stats=os.statvfs(p);assert 0<stats.f_blocks*stats.f_frsize<=256*1024*1024
large=p/'qa-bounded-allocation.tmp'
try:
 with large.open('wb') as stream:
  try:os.posix_fallocate(stream.fileno(),0,300*1024*1024)
  except OSError as e:assert e.errno==errno.ENOSPC
  else:raise AssertionError('physical quota did not refuse oversized allocation')
finally:large.unlink(missing_ok=True)
f=p/'qa-analysis.csv';f.write_text('amount\\n1\\n2\\n3\\n')
with f.open() as stream:total=sum(int(row['amount']) for row in csv.DictReader(stream))
assert total==6
(p/'qa-analysis-result.json').write_text(json.dumps({'total':total}))
print(json.dumps(dict(total=total,physical_quota_refused=True,uid=os.getuid(),capabilities=0,network='none',capacity_bytes=stats.f_blocks*stats.f_frsize)))
'''


def main():
    state=json.loads((ROOT/'prepared-pinned.json').read_text())
    wid=state['task']['workspace'].split('//')[1]
    path='/var/lib/zebra/erpnext-full-qa-workspaces/'+wid
    name=PREFIX+'-analysis'
    if name in subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines():
        raise ValueError('retained isolated sandbox requires inspection')
    started=time.monotonic()
    try:
        result=subprocess.run(['docker','run','--name',name,'--pull=never','--runtime','runsc',
            '--read-only','--network','none','--user','65532:65532','--cap-drop=ALL',
            '--security-opt','no-new-privileges','--memory','256m','--cpus','1','--pids-limit','32',
            '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m','-v',path+':/workspace:rw',
            '--entrypoint','python',RUNTIME,'-c',CODE],capture_output=True,text=True,timeout=30)
        if result.returncode:raise AssertionError(result.stderr[-1500:])
        output=dict(stage='real_private_gvisor_analysis',elapsed_ms=round((time.monotonic()-started)*1000,1),
            probe=json.loads(result.stdout),model_calls=0,search_calls=0,runtime_image=RUNTIME)
        (ROOT/'analysis-gate.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output))
    finally:
        subprocess.run(['docker','rm','-fv',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


if __name__=='__main__':main()
