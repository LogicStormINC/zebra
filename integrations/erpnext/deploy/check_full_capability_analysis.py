"""Cached digest-pinned gVisor analysis on the isolated private filesystem only."""

import json
import subprocess
import time
from pathlib import Path as Path

from prepare_full_capability_qa import PREFIX, ROOT, RUNTIME

CODE = (
    "import csv,errno,json,os,socket\nfrom pathlib import Path\np=Path("
    "'/workspace')\nassert os.getuid()==65532 and {n for _,n in socket"
    ".if_nameindex()}=={'lo'}\nassert int(next(s.split()[1] for s in P"
    "ath('/proc/self/status').read_text().splitlines() if s.startswit"
    "h('CapEff:')),16)==0\nstats=os.statvfs(p);assert 0<stats.f_blocks"
    "*stats.f_frsize<=256*1024*1024\nlarge=p/'qa-bounded-allocation.tm"
    "p'\ntry:\n with large.open('wb') as stream:\n  try:os.posix_falloca"
    "te(stream.fileno(),0,300*1024*1024)\n  except OSError as e:assert"
    " e.errno==errno.ENOSPC\n  else:raise AssertionError('physical quo"
    "ta did not refuse oversized allocation')\nfinally:large.unlink(mi"
    "ssing_ok=True)\nf=p/'qa-analysis.csv';f.write_text('amount\\n1\\n2\\"
    "n3\\n')\nwith f.open() as stream:total=sum(int(row['amount']) for "
    "row in csv.DictReader(stream))\nassert total==6\n(p/'qa-analysis-r"
    "esult.json').write_text(json.dumps({'total':total}))\nprint(json."
    "dumps(dict(total=total,physical_quota_refused=True,uid=os.getuid"
    "(),capabilities=0,network='none',capacity_bytes=stats.f_blocks*s"
    "tats.f_frsize)))\n"
)


def main():
    state = json.loads((ROOT / "prepared-pinned.json").read_text())
    wid = state["task"]["workspace"].split("//")[1]
    path = "/var/lib/zebra/erpnext-full-qa-workspaces/" + wid
    name = PREFIX + "-analysis"
    if (
        name
        in subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"], text=True
        ).splitlines()
    ):
        raise ValueError("retained isolated sandbox requires inspection")
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--name",
                name,
                "--pull=never",
                "--runtime",
                "runsc",
                "--read-only",
                "--network",
                "none",
                "--user",
                "65532:65532",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--pids-limit",
                "32",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=32m",
                "-v",
                path + ":/workspace:rw",
                "--entrypoint",
                "python",
                RUNTIME,
                "-c",
                CODE,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stderr[-1500:])
        output = dict(
            stage="real_private_gvisor_analysis",
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
            probe=json.loads(result.stdout),
            model_calls=0,
            search_calls=0,
            runtime_image=RUNTIME,
        )
        (ROOT / "analysis-gate.json").write_text(json.dumps(output, indent=2))
        print(json.dumps(output))
    finally:
        subprocess.run(
            ["docker", "rm", "-fv", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


if __name__ == "__main__":
    main()
