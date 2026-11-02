"""Fail closed before starting only this synthetic, resource-capped environment."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("root", type=Path)
parser.add_argument("--control", action="store_true")
parser.add_argument("--registry-only", action="store_true")
args = parser.parse_args()
root = args.root.resolve()
result = subprocess.run(
    [
        "docker",
        "compose",
        "--env-file",
        str(root / "compose.env"),
        "-f",
        str(root / "compose.yml"),
        "--profile",
        "control",
        "config",
        "--format",
        "json",
    ],
    capture_output=True,
    text=True,
    check=True,
)
config = json.loads(result.stdout)
assert (root / "check_model.py").is_file()
for name in (
    ("registry",) if args.registry_only else
    ("api", "worker", "node-tls", "broker", "authority", "model")
    if args.control
    else ("api", "worker", "node-tls")
):
    for mount in config["services"][name].get("volumes", []):
        if mount["type"] == "bind":
            path = Path(mount["source"])
            assert path.exists(), "required owned bind source missing"
            if path.suffix in {".crt", ".key", ".py", ".json"} or path.name.endswith("Caddyfile"):
                assert path.is_file(), "refusing a directory in place of fixture file"
assert config["name"] == "zebra-ha-e1-20261102"
for service in config["services"].values():
    assert service["labels"]["zebra.ha.owner"] == "ca-ha-03-e1-20261102"
    assert service["restart"] == "no"
    assert service["network_mode"] == "host"
    assert 0 < float(service["cpus"]) <= 2
    assert 0 < int(service["mem_limit"]) <= 2 * 1024**3
volume_name = config["volumes"]["workspaces"]["name"]
assert volume_name == "zebra-ha-e1-20261102-workspaces"
volume = json.loads(
    subprocess.check_output(["docker", "volume", "inspect", volume_name], text=True)
)[0]
assert volume["Labels"]["zebra.ha.owner"] == "ca-ha-03-e1-20261102"
assert volume["Driver"] == "local" and volume["Options"]["type"] == "tmpfs"
assert set(volume["Options"]["o"].split(",")) == {
    "size=512m",
    "uid=65532",
    "gid=65532",
    "mode=0770",
}
for name in (() if args.registry_only else ("api", "worker")):
    service = config["services"][name]
    assert float(service["cpus"]) == 2 and int(service["mem_limit"]) == 2 * 1024**3
    assert service["image"].startswith("sha256:")
    env = service["environment"]
    assert env["ZEBRA_RUNTIME_BUNDLE_CONFIG"] == "/e1/catalog.json"
    assert env["ZEBRA_PUBLICATION_MANAGEMENT_CONFIG"] == "/e1/publication.json"
    for filename in ("catalog.json", "publication.json"):
        info = (root / "execution" / filename).stat()
        assert info.st_uid == 65532 and info.st_mode & 0o777 in (0o400, 0o600)
    database = urlsplit(env["ZEBRA_DATABASE_URL"])
    assert (database.hostname, database.port, database.path) == ("127.0.0.1", 25432, "/ha_e1")
    assert env["ZEBRA_DEPLOYMENT_NAMESPACE"] == "ha-e1-20261102"
    assert env["ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA"] == "true"
    assert env["ZEBRA_WORKSPACE_VOLUME_ROOT"] == volume["Mountpoint"]
    assert any(
        v["type"] == "volume"
        and v["source"] == "workspaces"
        and v["target"] == volume["Mountpoint"]
        for v in service["volumes"]
    )
    assert env["ZEBRA_S3_ENDPOINT"] == "https://127.0.0.1:29000"
    assert env["ZEBRA_S3_BUCKET"] == "ha-e1-artifacts"
    assert env["ZEBRA_AUTHORITY_ISSUER"] == "https://127.0.0.1:28444"
    assert env["ZEBRA_MODEL_BASE_URL"] == "https://api.deepseek.com"
    assert service["extra_hosts"] in (
        ["api.deepseek.com=127.0.0.1"],
        {"api.deepseek.com": ["127.0.0.1"]},
        {"api.deepseek.com": "127.0.0.1"},
    )
    assert any(
        v["type"] == "bind"
        and v["source"] == str(root / "tls/ca.crt")
        and v["target"] == "/app/.venv/lib/python3.12/site-packages/certifi/cacert.pem"
        and v["read_only"]
        for v in service["volumes"]
    )
    redis = urlsplit(env["ZEBRA_LIVE_REDIS_URL"])
    assert (redis.scheme, redis.hostname, redis.port) == ("rediss", "127.0.0.1", 26379)
    for variable, user in (
        ("RELAY", "zebra-relay"),
        ("CONSUMER", "zebra-consumer"),
        ("SHADOW_CONSUMER", "zebra-shadow-consumer"),
    ):
        rabbit = urlsplit(env[f"ZEBRA_RABBIT_{variable}_URL"])
        assert (rabbit.scheme, rabbit.hostname, rabbit.port) == ("amqp", "127.0.0.1", 25672)
        assert rabbit.username == user and rabbit.path == "/%2Fzebra"
    assert "DEEPSEEK_API_KEY" not in env and "OPENAI_API_KEY" not in env
    budget = json.loads(env["ZEBRA_DATABASE_BUDGET_JSON"])
    total = sum(budget["fleet"].values()) * sum(
        budget[k] for k in ("pool", "normal", "read", "control", "probe")
    )
    assert total + budget["external"] + budget["server_reserved"] <= budget["max_connections"]
    assert budget["fleet"]["api"] == budget["fleet"]["worker"] == 2
    assert budget["execution_slots"] == 4
if args.registry_only:
    registry = config["services"]["registry"]
    assert registry["environment"]["REGISTRY_HTTP_ADDR"] == "127.0.0.1:28081"
    assert registry["image"] == (
        "registry@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
    )
    assert Path(registry["volumes"][0]["source"]) == (
        Path("/root/zebra-ha-e1-20261102/data/registry")
    )
if args.control or args.registry_only:
    data = Path(config["services"]["postgres"]["volumes"][0]["source"]).parent
    assert data == Path("/root/zebra-ha-e1-20261102/data")
    label = subprocess.check_output(["/usr/bin/findmnt", "-n", "-o", "LABEL", str(data)], text=True)
    assert label.strip() == "zebra_ha_e1"
    assert os.path.ismount(data), "dedicated data filesystem is not mounted"
    stats = os.statvfs(data)
    assert stats.f_blocks * stats.f_frsize <= 24 * 1024**3
print("E1 synthetic scope, quotas, budget and mount checks passed; no services started.")
