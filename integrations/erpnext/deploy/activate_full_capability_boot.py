"""Start only the new runtime after its private mounts/socket exist on reboot."""
from activate_full_capability import *


def main():
    state = json.loads((ROOT / 'prepared.json').read_text())
    assert state.get('activated') and state.get('new_conversation_enabled')
    unit = Path('/etc/systemd/system/zebra-erp-full-runtime.service')
    # Docker may auto-start containers before the quota mount propagation exists.
    # Reconcile this one Compose project again after its allocator is ready.
    text = f'''[Unit]
Description=ERP full runtime after private workspace mounts
After=docker.service zebra-erp-full-workspaces.service
Requires=docker.service zebra-erp-full-workspaces.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker compose -p {PREFIX} -f {ROOT}/compose.json up -d --pull never
TimeoutStartSec=120
[Install]
WantedBy=multi-user.target
'''
    candidate = ROOT / 'runtime-boot.service'
    if candidate.exists(): raise ValueError('boot unit exists; inspect original receipt')
    candidate.write_text(text)
    root('install', '-o', '0', '-g', '0', '-m', '644', str(candidate), str(unit))
    root('systemctl', 'daemon-reload')
    root('systemctl', 'enable', '--now', unit.name)
    root('systemctl', 'is-active', unit.name)
    print('new runtime ordered after private mounts; no reboot performed')


if __name__ == '__main__': main()
