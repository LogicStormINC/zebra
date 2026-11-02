"""Build one private, explicitly pinned node bundle; no remote operations."""

import argparse
import json
import re
import shutil
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("node", choices=("vm", "server"))
parser.add_argument("prepared", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--image", required=True)
args = parser.parse_args()
assert re.fullmatch(r"sha256:[a-f0-9]{64}", args.image)
source = args.prepared.resolve()
out = args.output.resolve()
out.mkdir(mode=0o700, parents=True, exist_ok=False)
vm = args.node == "vm"
root = "/root/zebra-ha-e1-20261102/runtime" if vm else ("/home/ubuntu/zebra-ha-e1-20261102/runtime")
settings = json.loads((source / "credentials.json").read_text())
rabbit = dict(line.split("=", 1) for line in (source / "rabbit.env").read_text().splitlines())
names = [
    "compose.yml",
    "Node.Caddyfile",
    "Control.Caddyfile",
    "verify.py",
    "check_model.py",
    "check_wire.py",
    "metering.py",
    "app.env",
]
if vm:
    names += [
        "broker.env",
        "init.sql",
        "fake_model.py",
        "model.py",
        "rabbit.env",
        "principals.json",
        "authority.py",
        "initialize.py",
        "rabbitmq.conf",
        "enabled_plugins",
        "provision_rabbitmq.py",
    ]
for name in names:
    shutil.copyfile(source / name, out / name)
    (out / name).chmod(0o600 if name.endswith((".env", ".json")) else 0o644)
(out / "tls").mkdir(mode=0o700)
for name in ["ca.crt", "server.crt", "server.key", "model.crt", "model.key"] + (
    ["pg.key", "broker.key"] if vm else []
):
    shutil.copyfile(source / "tls" / name, out / "tls" / name)
    (out / "tls" / name).chmod(0o600 if name.endswith(".key") else 0o644)
if not vm:
    (out / "broker.env").touch(mode=0o600)  # Inactive control profile still resolves env_file.
env = {
    "E1_ROOT": root,
    "E1_IMAGE": args.image,
    "E1_WORKER_ID": f"ha-e1-{args.node}",
    "E1_DOCKER_GID": "104" if vm else "984",
    "E1_CERT_UID": "0" if vm else "1000",
    "E1_CERT_GID": "0" if vm else "1000",
    "E1_WORKSPACE_VOLUME": "zebra-ha-e1-20261102-workspaces",
    "E1_WORKSPACE_PATH": "/var/lib/docker/volumes/zebra-ha-e1-20261102-workspaces/_data",
    "E1_DATA": "/root/zebra-ha-e1-20261102/data",
    "E1_CADDY_IMAGE": (
        "caddy@sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5"
    ),
    "E1_POSTGRES_IMAGE": (
        "postgres@sha256:5d004e058f520673f1f6edbad6b1603d5dab4c818e257c041889ef64672a8cc4"
    ),
    "E1_REDIS_IMAGE": (
        "redis@sha256:987c376c727652f99625c7d205a1cba3cb2c53b92b0b62aade2bd48ee1593232"
    ),
    "E1_MINIO_IMAGE": (
        "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/quay.io/minio/minio@sha256:"
        "5df32c340d4d98309cf9c3220bd20883429ba6cd24a34827dad1658b610e65ca"
    ),
    "E1_PG_ADMIN_PASSWORD": settings["pg_admin"] if vm else "unused-on-server",
    "E1_REDIS_PASSWORD": settings["redis"] if vm else "unused-on-server",
    "E1_S3_ACCESS": "ha-e1",
    "E1_S3_SECRET": settings["s3_secret"] if vm else "unused-on-server",
    "E1_RABBIT_ADMIN_PASSWORD": rabbit["RABBITMQ_ADMIN_PASSWORD"] if vm else "unused-on-server",
}
path = out / "compose.env"
path.touch(mode=0o600)
path.write_text("\n".join(f"{key}={value}" for key, value in env.items()) + "\n")
archive = out.with_suffix(".tar.gz")
assert not archive.exists()
archive.touch(mode=0o600)
with tarfile.open(archive, "w:gz") as bundle:
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        info = bundle.gettarinfo(str(path), arcname=str(path.relative_to(out)))
        owner = (
            70
            if path.name == "pg.key"
            else 65532
            if path.name == "broker.key"
            else 0
            if vm
            else 1000
        )
        info.uid = info.gid = owner
        info.uname = info.gname = ""
        with path.open("rb") as stream:
            bundle.addfile(info, stream)
print("Private pinned node bundle written; CA signing key excluded; no services started.")
