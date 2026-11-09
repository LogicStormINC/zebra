"""Operator-only cold gVisor/image smoke; no real workspace or provider request."""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/erpnext/zebra-agent/capability-upgrade-20261028-1")
NAME = "erp-agent-capability-qa-sandbox-20261028-1"
CODE = """import json,os,socket,sys,tempfile
assert os.getuid()==65532
status=open('/proc/self/status').read()
caps=next(line.split()[1] for line in status.splitlines() if line.startswith('CapEff:'))
assert int(caps,16)==0
assert {name for _,name in socket.if_nameindex()}=={'lo'}
with tempfile.TemporaryFile() as f:
 f.write(b'isolated scratch');f.seek(0);assert f.read()==b'isolated scratch'
print(json.dumps({'python':sys.version.split()[0],'uid':os.getuid(),'effective_capabilities':0,'interfaces':['lo'],'scratch_ok':True}))
"""


def main():
    output = ROOT / "sandbox.json"
    if output.exists():
        raise ValueError("Refusing to replace earlier sandbox evidence")
    if (
        NAME
        in subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"], text=True
        ).splitlines()
    ):
        raise ValueError("Inspect the existing owned sandbox first")
    image = json.loads((ROOT / "candidate.json").read_text())["candidate_runtime_image"]
    subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--name",
                NAME,
                "--pull",
                "never",
                "--runtime",
                "runsc",
                "--network",
                "none",
                "--read-only",
                "--user",
                "65532:65532",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--pids-limit",
                "32",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m",
                "--entrypoint",
                "python",
                image,
                "-c",
                CODE,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        evidence = {
            "image": image,
            "exit_code": result.returncode,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "model_calls": 0,
            "search_calls": 0,
            "real_workspace_mounted": False,
            "quota_and_native_composition_tested": False,
        }
        if result.returncode == 0:
            evidence["probe"] = json.loads(result.stdout)
            inspected = json.loads(subprocess.check_output(["docker", "inspect", NAME]))[0]
            assert inspected["HostConfig"]["Runtime"] == "runsc"
            assert inspected["HostConfig"]["NetworkMode"] == "none"
            assert inspected["HostConfig"]["ReadonlyRootfs"] is True
            assert not inspected["Mounts"] or all(m["Type"] == "tmpfs" for m in inspected["Mounts"])
        else:
            evidence["error"] = result.stderr[-2000:]
        output.write_text(json.dumps(evidence, indent=2) + "\n")
        output.chmod(0o600)
        assert result.returncode == 0, "Cold sandbox failed; retained evidence"
        print(json.dumps(evidence), flush=True)
    finally:
        subprocess.run(
            ["docker", "rm", "-fv", NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


if __name__ == "__main__":
    main()
