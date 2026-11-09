#!/usr/bin/env bash
set -euo pipefail

namespace=${1:?expected rebuilt corpus namespace}
[[ "$namespace" =~ ^e1-corpus-[a-f0-9]{32}$ ]]
old=zebra-e1-postgres-rebuilt-corpus
new=$old-tls
volume=$old-data
db=zebra_e1_corpus_rebuilt
owner=ca-ha-03-e1-20261102

exec 9>/run/lock/zebra-e1-rebuilt-postgres.lock
flock -n 9
for container in "$old" "$new"; do
    test "$(docker inspect -f '{{index .Config.Labels "zebra.ha.owner"}}' "$container")" = "$owner"
    test "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$container")" = "$volume"
done
test "$(docker inspect -f '{{.State.Status}}' "$old")" = running
case "$(docker inspect -f '{{.State.Status}}' "$new")" in
    created|exited) ;;
    *) exit 1 ;;
esac
test "$(docker ps --filter "volume=$volume" --format '{{.Names}}')" = "$old"

proof=$(docker exec -i "$old" psql -U postgres -d "$db" -qAt -v ON_ERROR_STOP=1 <<SQL
BEGIN READ ONLY;
SELECT
  (SELECT count(*) FROM agent_tasks WHERE deployment_namespace='$namespace'),
  (SELECT count(*) FROM session_events WHERE deployment_namespace='$namespace'),
  (SELECT count(*) FROM control_plane_epochs WHERE deployment_namespace='$namespace'),
  (SELECT backfill_state FROM command_wakeup_rollouts WHERE deployment_namespace='$namespace');
COMMIT;
SQL
)
if [[ "$proof" != '10000|1000000|1|complete' ]]; then
    printf 'E1 corpus cutover gate incomplete (%s)\n' "$proof" >&2
    exit 1
fi
if [[ "${2:-}" == --check ]]; then
    printf '%s\n' "$proof"
    exit 0
fi
test "$#" = 1

docker stop "$old" >/dev/null
test -z "$(docker ps --filter "volume=$volume" --format '{{.Names}}')"
if docker start "$new" >/dev/null; then
    for ((attempt=0; attempt<30; attempt++)); do
        if docker exec -u postgres "$new" psql -p 25432 -d "$db" -qAtc 'SELECT 1' >/dev/null 2>&1; then
            printf '%s\n' "$proof"
            exit 0
        fi
        sleep 1
    done
fi
docker stop "$new" >/dev/null
test -z "$(docker ps --filter "volume=$volume" --format '{{.Names}}')"
docker start "$old" >/dev/null
exit 1
