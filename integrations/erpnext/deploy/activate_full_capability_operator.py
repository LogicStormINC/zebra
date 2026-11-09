"""Install persistent quota operator for new production roots; existing roots untouched."""

import json
import secrets
import subprocess

from activate_full_capability import (
    DB as DB,
)
from activate_full_capability import (
    HOST as HOST,
)
from activate_full_capability import (
    NATIVE as NATIVE,
)
from activate_full_capability import (
    NETWORK as NETWORK,
)
from activate_full_capability import (
    PREFIX as PREFIX,
)
from activate_full_capability import (
    ROOT as ROOT,
)
from activate_full_capability import (
    Path as Path,
)
from activate_full_capability import (
    env as env,
)
from activate_full_capability import (
    private as private,
)
from activate_full_capability import (
    root as root,
)
from activate_full_capability import (
    run as run,
)


def main():
    if not (ROOT / "prepared.json").exists():
        raise ValueError("prepared production dependencies required")
    operator = Path("/etc/zebra/erp-full")
    socket = Path("/run/zebra-erp-full")
    volume = Path("/var/lib/zebra/erpnext-full-workspaces")
    state = Path("/var/lib/zebra/erpnext-full-volumes")
    if operator.exists() or socket.exists() or volume.exists() or state.exists():
        raise ValueError("owned operator paths exist; inspect before continuing")
    for p in [operator, socket, volume, state]:
        root("install", "-d", "-o", "0", "-g", "0", "-m", "755", str(p))
    root("chown", "0:65532", str(socket))
    root("chmod", "750", str(socket))
    password = secrets.token_hex(32)
    sql = (
        "CREATE ROLE erpnext_full_proof LOGIN PASSWORD '"
        f"{password}"
        "';GRANT CONNECT ON DATABASE "
        f"{DB}"
        " TO erpnext_full_proof;GRANT USAGE ON SCHEMA public TO erpnext_f"
        "ull_proof;GRANT SELECT ON ALL TABLES IN SCHEMA public TO erpnext"
        "_full_proof;ALTER ROLE erpnext_full_proof SET default_transactio"
        "n_read_only=on;ALTER ROLE erpnext_full_proof SET statement_timeo"
        "ut='5s';"
    )
    run(
        "docker",
        "exec",
        "-i",
        PREFIX + "-postgres-1",
        "psql",
        "-U",
        "erpnext_full",
        "-d",
        DB,
        "-v",
        "ON_ERROR_STOP=1",
        input=sql.encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    config = dict(
        generation="cloud114",
        helper_image=NATIVE,
        helper_network=NETWORK,
        helper_hostname=HOST,
        readonly_dsn=f"postgresql://erpnext_full_proof:{password}@native-full-db:5432/{DB}",
        host_tool_shared_secret=env(ROOT / "api.env")["ZEBRA_HOST_TOOL_SHARED_SECRET"],
        host_ca_file=str(operator / "runtime.crt"),
        worker_host_uid=65532,
        hmac_key_path=str(operator / "hmac.key"),
        socket_path=str(socket / "allocator.sock"),
    )
    private(ROOT / "allocator-config.json", json.dumps(config))
    key = ROOT / "allocator.key"
    key.write_bytes(secrets.token_bytes(32))
    key.chmod(0o600)
    # Mount setup is idempotent only for these newly owned fixed roots. No format,
    # image deletion or global mount propagation change is performed here.
    prepare = (
        "import os,subprocess\nfrom pathlib import Path\nroot=Path('/var/li"
        "b/zebra/erpnext-full-workspaces');state=Path('/var/lib/zebra/erp"
        "next-full-volumes');source=Path('/data/erpnext-agent-full/worksp"
        "ace-volumes')\nfor p in [root,state,source]:\n if p.is_symlink() o"
        "r not p.is_dir() or p.stat().st_uid!=0 or p.stat().st_mode&0o022"
        ":raise ValueError('unsafe full root')\nif not state.is_mount():su"
        "bprocess.run(['mount','--bind',str(source),str(state)],check=Tru"
        "e)\nif not root.is_mount():\n subprocess.run(['mount','--bind',str"
        "(root),str(root)],check=True)\n subprocess.run(['mount','--make-p"
        "rivate',str(root)],check=True)\n subprocess.run(['mount','--make-"
        "shared',str(root)],check=True)\nsocket=Path('/run/zebra-erp-full'"
        ");socket.mkdir(exist_ok=True,mode=0o750);os.chown(socket,0,65532"
        ");os.chmod(socket,0o750)\nsubprocess.run(['install','-o','0','-g'"
        ",'65532','-m','640','/etc/zebra/erp-full/hmac.key',str(socket/'k"
        "ey')],check=True)\n"
    )
    (ROOT / "prepare-mount.py").write_text(prepare)
    unit = (
        "[Unit]\nDescription=ERP full-runtime private quota allocator\nAfte"
        "r=docker.service local-fs.target network-online.target\nRequires="
        "docker.service\nRequiresMountsFor=/data/erpnext-agent-full\n[Servi"
        "ce]\nType=simple\nUser=root\nPrivateTmp=no\nExecStartPre=/usr/bin/py"
        "thon3 /etc/zebra/erp-full/prepare-mount.py\nExecStart=/usr/bin/py"
        "thon3 /etc/zebra/erp-full/private_workspace_operator.py /etc/zeb"
        "ra/erp-full/config.json\nRestart=on-failure\nRestartSec=5\n[Install"
        "]\nWantedBy=multi-user.target\n"
    )
    (ROOT / "operator.service").write_text(unit)
    for source, destination, mode in [
        (ROOT / "allocator-config.json", operator / "config.json", "600"),
        (key, operator / "hmac.key", "600"),
        (ROOT / "tls/runtime.crt", operator / "runtime.crt", "644"),
        *[
            (ROOT / name, operator / name, "644")
            for name in (
                "private_workspace_allocator.py",
                "private_workspace_native_proof.py",
                "private_workspace_operator.py",
            )
        ],
        (ROOT / "prepare-mount.py", operator / "prepare-mount.py", "644"),
        (
            ROOT / "operator.service",
            Path("/etc/systemd/system/zebra-erp-full-workspaces.service"),
            "644",
        ),
    ]:
        root("install", "-o", "0", "-g", "0", "-m", mode, str(source), str(destination))
    root("systemctl", "daemon-reload")
    root(
        "systemctl",
        "enable",
        "--now",
        "zebra-erp-full-workspaces.service",
        stdout=subprocess.DEVNULL,
    )
    print(
        json.dumps(
            dict(
                stage="persistent_production_quota_operator_active",
                quota_bytes=256 * 1024 * 1024,
                existing_workspaces_untouched=True,
            )
        )
    )


if __name__ == "__main__":
    main()
