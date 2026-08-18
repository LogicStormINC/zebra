#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/tests/compose/recovery_backup/compose.yml"
PROJECT="zebra-pg-recovery-backup-test"
PORT="${ZEBRA_PG_RECOVERY_BACKUP_POSTGRES_PORT:-25462}"
export ZEBRA_PG_RECOVERY_BACKUP_POSTGRES_PORT="$PORT"
COMPOSE=(docker compose --project-name "$PROJECT" --file "$COMPOSE_FILE")
TEMP_DIR=$(mktemp -d)
DUMP_FILE="$TEMP_DIR/zebra.dump"
EXPECTED_FILE="$TEMP_DIR/expected.json"
MANIFEST_FILE="$TEMP_DIR/backup-manifest.json"

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --detach --wait postgres

SOURCE_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra"
RESTORE_DSN="postgresql://zebra:zebra-test-password@127.0.0.1:${PORT}/zebra_restore"

(
  cd "$ROOT_DIR"
  uv run --package agent-storage python tests/compose/recovery_backup/verify_backup.py \
    --mode seed --dsn "$SOURCE_DSN" --expected "$EXPECTED_FILE"
)

"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  pg_dump -U zebra -d zebra --format=custom --no-owner --no-privileges > "$DUMP_FILE"
test -s "$DUMP_FILE"
DUMP_SHA=$(sha256_file "$DUMP_FILE")
DUMP_BYTES=$(wc -c < "$DUMP_FILE" | tr -d '[:space:]')
printf '{"archive_format":"custom","bytes":%s,"no_owner":true,"no_privileges":true,"sha256":"%s"}\n' \
  "$DUMP_BYTES" "$DUMP_SHA" > "$MANIFEST_FILE"

"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  createdb -U zebra --template=template0 zebra_restore
"${COMPOSE[@]}" exec -T -e PGPASSWORD=zebra-test-password postgres \
  pg_restore --exit-on-error --no-owner --no-privileges -U zebra -d zebra_restore < "$DUMP_FILE"

(
  cd "$ROOT_DIR"
  uv run --package agent-storage python tests/compose/recovery_backup/verify_backup.py \
    --mode verify --dsn "$RESTORE_DSN" --expected "$EXPECTED_FILE"
)

test -s "$MANIFEST_FILE"
MANIFEST_SHA=$(sed -nE 's/.*"sha256":"([0-9a-f]+)".*/\1/p' "$MANIFEST_FILE")
test "$MANIFEST_SHA" = "$DUMP_SHA"
printf 'RECOVERY_BACKUP_MANIFEST=PASS sha256=%s bytes=%s\n' "$MANIFEST_SHA" "$DUMP_BYTES"
echo "ZEBRA_PG_RECOVERY_BACKUP_TEST_RESULT=PASS"
