#!/bin/sh
# Run once as root. The existing Cloud image requires a dedicated quota mount.
set -eu
image=/opt/erpnext/zebra-agent/workspace.ext4
root=/var/lib/zebra/erpnext-workspaces
if ! mountpoint -q "$root"; then
    if [ ! -e "$image" ]; then
        truncate -s 1G "$image"
        mkfs.ext4 -q -m 0 "$image"
    fi
    mkdir -p "$root"
    mount -o loop,nosuid,nodev "$image" "$root"
fi
chown 65532:65532 "$root"
# ponytail: reuse the native single-root layout with one serial Worker. The
# runtime is read-only; business data stays behind Host tools. Writable/code
# workloads require per-task quota mounts before enabling those capabilities.
line="$image $root ext4 loop,nosuid,nodev 0 0"
if ! grep -Fqx "$line" /etc/fstab; then printf '%s\n' "$line" >> /etc/fstab; fi
