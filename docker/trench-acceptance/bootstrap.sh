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

ca_refreshed=false
if [[ ! -f "$secrets/ca.crt" || ! -f "$secrets/ca.key" ]] \
  || ! openssl x509 -checkend 86400 -noout -in "$secrets/ca.crt" >/dev/null 2>&1; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout "$secrets/ca.key" -out "$secrets/ca.crt" \
    -subj "/CN=Zebra Trench Acceptance CA" >/dev/null 2>&1
  ca_refreshed=true
fi

if [[ "$ca_refreshed" == true || ! -f "$secrets/tls.crt" || ! -f "$secrets/tls.key" ]] \
  || ! openssl x509 -checkend 86400 -noout -in "$secrets/tls.crt" >/dev/null 2>&1 \
  || ! openssl x509 -in "$secrets/tls.crt" -noout -text | grep -q "DNS:zebra.localhost"; then
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

# HTTPX honors SSL_CERT_FILE as one complete trust store.  Keep the public
# roots required by model providers and append the private acceptance CA used
# by the Host and Grant Broker endpoints.
(cd "$here/../.." && uv run python - "$secrets/ca.crt" "$secrets/ca-bundle.crt" <<'PY'
from pathlib import Path
import sys

import certifi

private_ca = Path(sys.argv[1]).read_bytes().rstrip() + b"\n"
public_roots = Path(certifi.where()).read_bytes().rstrip() + b"\n"
Path(sys.argv[2]).write_bytes(public_roots + private_ca)
PY
)
chmod 600 "$secrets/ca-bundle.crt"

echo "bootstrap complete; CA certificate for callers: $secrets/ca.crt"
