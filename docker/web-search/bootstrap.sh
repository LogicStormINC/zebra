#!/usr/bin/env bash
# Operator-only: generate service secrets, never start or restart containers.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ca_dir="${ZEBRA_SEARCH_CA_DIR:-$here/../trench-acceptance/secrets}"
secrets="${ZEBRA_SEARCH_SECRETS_DIR:-$here/secrets}"
for required in ca.crt ca.key ca-bundle.crt; do
  test -f "$ca_dir/$required" || { echo "missing acceptance $required; bootstrap acceptance CA first" >&2; exit 1; }
done
openssl x509 -checkend 86400 -noout -in "$ca_dir/ca.crt" >/dev/null
mkdir -p "$secrets"
chmod 700 "$secrets"
if [[ ! -f "$secrets/service.env" ]]; then
  (umask 077; printf 'SEARXNG_SECRET=%s\n' "$(openssl rand -hex 32)" > "$secrets/service.env")
fi
if [[ ! -f "$secrets/search.crt" || ! -f "$secrets/search.key" ]] \
  || ! openssl x509 -checkend 86400 -noout -in "$secrets/search.crt" >/dev/null 2>&1 \
  || ! openssl verify -CAfile "$ca_dir/ca.crt" "$secrets/search.crt" >/dev/null 2>&1; then
  openssl req -newkey rsa:2048 -nodes -keyout "$secrets/search.key" \
    -out "$secrets/search.csr" -subj '/CN=search.zebra.test' >/dev/null 2>&1
  openssl x509 -req -in "$secrets/search.csr" -days 14 \
    -CA "$ca_dir/ca.crt" -CAkey "$ca_dir/ca.key" \
    -set_serial "0x$(openssl rand -hex 16)" -out "$secrets/search.crt" \
    -extfile <(printf 'subjectAltName=DNS:search.zebra.test\nextendedKeyUsage=serverAuth\n') >/dev/null 2>&1
fi
chmod 600 "$secrets/service.env" "$secrets/search.key"
echo 'search secrets prepared; existing CA, environment and running services unchanged'
