#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
case ${1:-} in
    cruza) source_name=cruza; port=15610 ;;
    quadpi) source_name=quadpi; port=15611 ;;
    *) echo 'Specify cruza or quadpi'; exit 2 ;;
esac
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/var/backups/cruza-fleet-observer/$stamp
install -d -m 700 "$backup"
for file in /opt/cruza-telemetry-tap.py /opt/cruza-telemetry-relay.py /etc/systemd/system/cruza-telemetry-observer.service; do
    [[ ! -e $file ]] || cp -a --parents "$file" "$backup/"
done
python3 -m py_compile telemetry-tap.py telemetry-relay.py
install -m 644 telemetry-tap.py /opt/cruza-telemetry-tap.py
install -m 644 telemetry-relay.py /opt/cruza-telemetry-relay.py
cat > /etc/systemd/system/cruza-telemetry-observer.service <<EOF
[Unit]
Description=Optional passive fleet telemetry observer ($source_name)
StartLimitIntervalSec=300
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/cruza-telemetry-tap.py --source $source_name --local-port $port
Restart=on-failure
RestartSec=30
Nice=19
CPUQuota=5%
MemoryMax=24M
TasksMax=4
CapabilityBoundingSet=CAP_NET_RAW CAP_SETUID CAP_SETGID
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_PACKET AF_INET
LogRateLimitIntervalSec=60
LogRateLimitBurst=3

[Install]
WantedBy=multi-user.target
EOF
systemd-analyze verify /etc/systemd/system/cruza-telemetry-observer.service
systemctl daemon-reload
systemctl enable --now cruza-telemetry-observer.service
echo "Observer installed; backup: $backup"
systemctl is-active cruza-telemetry-observer.service
