#!/usr/bin/env bash
# P2 wiring: point the running Trench stack at the Zebra acceptance stack.
# Idempotent; run on the acceptance server.
set -euo pipefail

ZEbra_HOME=~/zebra-agent
CA_SRC=$ZEbra_HOME/docker/trench-acceptance/secrets/ca.crt

echo "=== 1. workspace tmpfs (no-op if already mounted) ==="
if ! mountpoint -q /var/lib/zebra/workspaces; then
  echo root | sudo -S bash -c \
    "mkdir -p /var/lib/zebra/workspaces && mount -t tmpfs -o size=8g,nosuid,nodev tmpfs /var/lib/zebra/workspaces"
  echo mounted
else
  echo already-mounted
fi

echo "=== 2. locate Trench compose project ==="
WORKDIR=$(sg docker -c "docker inspect trench-api --format '{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}'")
PROJECT=$(sg docker -c "docker inspect trench-api --format '{{index .Config.Labels \"com.docker.compose.project\"}}'")
echo "trench project=$PROJECT workdir=$WORKDIR"
cd "$WORKDIR"

echo "=== 3. env values ==="
ENV_FILE="${ENV_FILE:-.env}"
[ -f "$ENV_FILE" ] || ENV_FILE="env.deploy"
touch "$ENV_FILE"
python3 - "$ENV_FILE" <<'EOF'
import sys
path = sys.argv[1]
values = {
    "TRENCH_AI_STRATEGY_RUNTIME": "zebra",
    "ZEBRA_AGUI_URL": "https://zebra.zebra.local:8443",
    "ZEBRA_AGUI_COMMAND_URL": "https://zebra.zebra.local:8443/agui/commands",
    "ZEBRA_AGUI_STREAM_BASE_URL": "https://zebra.zebra.local:8443",
    "ZEBRA_TASKS_URL": "https://zebra.zebra.local:8443/tasks",
    "ZEBRA_HOST_GRANT_EXCHANGE_URL": "https://broker.zebra.local:8443/exchange",
    "ZEBRA_BFF_TIMEOUT_MS": "15000",
    "ZEBRA_BFF_REQUIRE_HTTPS": "true",
    "TRENCH_AI_HOST_TOOL_WORKLOAD_IDENTITIES": "trench-read-only",
    "TRENCH_AI_HOST_TOOL_SHARED_SECRET": "compat:trench-read-v1",
}
lines = open(path).read().splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip()
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")
open(path, "w").write("\n".join(out) + "\n")
print("env updated:", path)
EOF

echo "=== 4. compose patch: CA trust + shared network for trench-api ==="
cp -f "$CA_SRC" ./docker/zebra-acceptance-ca.crt
python3 - <<'EOF'
from pathlib import Path
import sys
compose = None
for candidate in ("docker/compose.prod.yml", "compose.prod.yml"):
    if Path(candidate).exists():
        compose = candidate
        break
if compose is None:
    sys.exit("compose.prod.yml not found")
text = Path(compose).read_text()
if "zebra-acceptance-ca.crt" not in text:
    text = text.replace(
        "  trench-api:\n    <<: *backend-service\n    container_name: trench-api\n",
        "  trench-api:\n    <<: *backend-service\n    container_name: trench-api\n"
        "    volumes:\n"
        "      - ./zebra-acceptance-ca.crt:/etc/ssl/certs/zebra-acceptance.crt:ro\n"
        "    networks: [default, zebra-dependencies]\n",
    )
    text = text.replace(
        "      ZEBRA_AGUI_URL: ${ZEBRA_AGUI_URL:-}",
        "      ZEBRA_AGUI_URL: ${ZEBRA_AGUI_URL:-}\n"
        "      SSL_CERT_FILE: /etc/ssl/certs/zebra-acceptance.crt",
    )
    if "zebra-dependencies:" not in text.split("networks:")[-1]:
        text += (
            "\nnetworks:\n"
            "  zebra-dependencies:\n"
            "    name: zebra-dependencies\n"
            "    external: true\n"
        )
    Path(compose).write_text(text)
    print("compose patched:", compose)
else:
    print("compose already patched")
EOF

echo "=== 5. recreate trench-api ==="
sg docker -c "docker compose -p $PROJECT -f $(ls docker/compose.prod.yml compose.prod.yml 2>/dev/null | head -1) up -d trench-api" || \
sg docker -c "docker compose up -d trench-api"
sleep 10
sg docker -c "docker ps --format '{{.Names}}\t{{.Status}}'" | grep trench-api
echo "=== 6. zebra worker healthy? ==="
sg docker -c "docker ps --format '{{.Names}}\t{{.Status}}'" | grep zebra-application
echo "P2 WIRING DONE"
