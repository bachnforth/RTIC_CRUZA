#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
python3 /opt/cruza/cruza.py validate
# Only the configured Android tailnet IP may send MAVLink to the private listener.
# This owns a separate table and never flushes the host firewall.
python3 - <<'PY' > /run/cruza-firewall.nft
import sys
sys.path.insert(0, '/opt/cruza')
from cruza import config, tail_ip
c = config('/etc/cruza/config.json')
# Primary Android plus any extra GCS phones in android_ip2 (str or list).
peers = [tail_ip(c['android_ip'])]
extra = c.get('android_ip2') or []
for e in ([extra] if isinstance(extra, str) else extra):
    if e:
        peers.append(tail_ip(e))
port = c['mavlink_port']
print('table inet cruza {')
print('chain input {')
print('type filter hook input priority -10; policy accept;')
for p in peers:
    print(f'udp dport {port} iifname "tailscale0" ip saddr {p} accept')
print(f'udp dport {port} drop')
print('}')
print('}')
PY
nft --check --file /run/cruza-firewall.nft
# Initial activation only: refuse to replace an existing policy without review.
if nft list table inet cruza >/dev/null 2>&1; then
    echo 'Cruza firewall exists; inspect before changing peer/port. No replacement made.'
    exit 1
fi
install -m 644 /run/cruza-firewall.nft /etc/cruza/firewall.nft
systemctl enable --now cruza-firewall.service
systemctl enable --now cruza-router.service
