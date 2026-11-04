#!/usr/bin/env bash
set -euo pipefail

scratch=$(mktemp -d)
trap 'unlink "$scratch/gvisor.tar.zstd" 2>/dev/null || true; unlink "$scratch/gvisor.tar.zstd.sha512" 2>/dev/null || true; rmdir "$scratch"' EXIT
cd "$scratch"
arch="$(uname -m)"
release="https://storage.googleapis.com/gvisor/releases/release/latest/${arch}"
curl --fail --silent --show-error --location --remote-name "${release}/gvisor.tar.zstd"
curl --fail --silent --show-error --location --remote-name "${release}/gvisor.tar.zstd.sha512"
sha512sum --check gvisor.tar.zstd.sha512
sudo tar --zstd -xf gvisor.tar.zstd -C /usr/local/bin
sudo /usr/local/bin/runsc install
sudo systemctl restart docker
