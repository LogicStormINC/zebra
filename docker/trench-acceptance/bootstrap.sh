#!/usr/bin/env bash
# Bootstrap secrets for the Trench acceptance environment:
#   1. an RSA keypair for the Host Grant broker (if missing)
#   2. a local CA + TLS certificate for Docker aliases and host-facing localhost names
# Secrets land in docker/trench-acceptance/secrets/ which is git-ignored.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
secrets="$here/secrets"
mkdir -p "$secrets"
chmod 700 "$secrets"

if [[ ! -f "$secrets/trench-host-grant-v1.pem" ]]; then
  (cd "$here/../.." && uv run python -m zebra_host_grant_broker.keys "$secrets" trench-host-grant-v1)
  echo "generated broker keypair in $secrets"
fi

if [[ ! -f "$secrets/ca.crt" || ! -f "$secrets/ca.key" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout "$secrets/ca.key" -out "$secrets/ca.crt" \
    -subj "/CN=Zebra Trench Acceptance CA" >/dev/null 2>&1
fi

if [[ ! -f "$secrets/tls.crt" ]] || ! openssl x509 -in "$secrets/tls.crt" -noout -text | grep -q "DNS:zebra.localhost"; then
  openssl req -newkey rsa:2048 -nodes \
    -keyout "$secrets/tls.key" -out "$secrets/tls.csr" \
    -subj "/CN=zebra.zebra.local" >/dev/null 2>&1
  openssl x509 -req -in "$secrets/tls.csr" -days 30 \
    -CA "$secrets/ca.crt" -CAkey "$secrets/ca.key" -CAcreateserial \
    -out "$secrets/tls.crt" \
    -extfile <(printf "subjectAltName=IP:127.0.0.1,DNS:zebra.localhost,DNS:broker.localhost,DNS:zebra.zebra.local,DNS:broker.zebra.local,DNS:trench.zebra.local") >/dev/null 2>&1
  rm -f "$secrets/tls.csr"
  echo "generated local acceptance certificate in $secrets"
fi

echo "bootstrap complete; CA certificate for callers: $secrets/ca.crt"
