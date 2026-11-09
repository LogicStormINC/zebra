#!/bin/bash
set -euo pipefail
run="$(date +%s)-$$"
net=zebra-proof-$run
primary=$net-pg
replica=$net-r
replacement=$net-r2
image=postgres:17.5-alpine3.21
docker network create --internal "$net" >/dev/null
cleanup() {
 status=$?
 for container in "$replacement" "$replica" "$primary"; do
  if docker inspect "$container" >/dev/null 2>&1; then
    if test "$status" != 0; then docker logs --tail 20 "$container" >&2; fi
    docker rm -f -v "$container" >/dev/null
  fi
 done
 docker network rm "$net" >/dev/null
}
trap cleanup EXIT
sql() { docker exec -i "$1" psql -XqAt -v ON_ERROR_STOP=1 -U postgres -d postgres "${@:2}"; }
ready() {
 for i in {1..60}; do
  if docker exec "$1" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then return; fi
  sleep .25
 done
 return 1
}
stream() {
 docker run --name "$1" --network "$net" -d --entrypoint sh "$image" -ec '
  chown postgres:postgres "$PGDATA"; chmod 700 "$PGDATA"
  gosu postgres pg_basebackup -h "$1" -U postgres -D "$PGDATA" -X stream -R -c fast
  exec gosu postgres postgres -c listen_addresses="*"
 ' _ "$2" >/dev/null
 ready "$1"
}
docker run --name "$primary" --network "$net" -e POSTGRES_HOST_AUTH_METHOD=trust -d "$image" >/dev/null
ready "$primary"
docker exec "$primary" sh -c 'echo "host replication postgres all trust" >> "$PGDATA/pg_hba.conf"'
sql "$primary" -c 'SELECT pg_reload_conf()' >/dev/null
sql "$primary" <<'SQL'
CREATE ROLE e1_receipt_reader LOGIN;
CREATE TABLE control_plane_idempotency_records (
deployment_namespace text, action text, idempotency_key text, request_hash text,
status_code integer, response_body jsonb);
INSERT INTO control_plane_idempotency_records VALUES ('proof','run','key','digest',201,'{"sealed":"fixture"}');
SQL
sql "$primary" < tests/compose/cloud_ha_e1/standby_receipt_proof.sql
identity=$(sql "$primary" -c "SELECT system_identifier FROM pg_control_system()")
proof() {
 sql "$1" -c "SET ROLE e1_receipt_reader; SELECT public.e1_confirm_receipt('$identity','$2','proof','run','key','digest',201,'{\"sealed\":\"fixture\"}')"
}
stream "$replica" "$primary"
for i in {1..30}; do
 if test "$(proof "$replica" 1)" = t; then break; fi
 sleep .25
done
test "$(proof "$replica" 1)" = t
test "$(proof "$replica" 2)" = f
printf '%s\n' 'timeline_1_matches; expected_timeline_2_rejects_same_system'
docker stop "$primary" >/dev/null
for i in {1..30}; do
 if test "$(proof "$replica" 1)" = f; then break; fi
 sleep .25
done
test "$(proof "$replica" 1)" = f
printf '%s\n' 'disconnected_old_replica_cannot_prove_receipt'
test "$(sql "$replica" -c 'SELECT pg_promote(true,10)')" = t
test "$(proof "$replica" 2)" = f
printf '%s\n' 'promoted_writer_cannot_prove_receipt'
stream "$replacement" "$replica"
for i in {1..30}; do
 if test "$(proof "$replacement" 2)" = t; then break; fi
 sleep .25
done
test "$(proof "$replacement" 2)" = t
test "$(proof "$replacement" 1)" = f
test "$(sql "$replacement" -c "SET ROLE e1_receipt_reader; SELECT public.e1_confirm_receipt('$identity','2','proof','run','key','other',201,'{\"sealed\":\"fixture\"}')")" = f
printf '%s\n' 'replacement_on_timeline_2_matches; old_timeline_and_wrong_receipt_rejected'
