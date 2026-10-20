#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this installer with sudo on the Pi.' >&2
    exit 1
fi
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
test -f /etc/cruza/config.json
id ebach >/dev/null
/usr/bin/python3 - "$source_dir" <<'PY'
from pathlib import Path
import sys
for name in ('comms-health.py', 'flight-health.py'):
    path = Path(sys.argv[1])/name
    compile(path.read_text(), str(path), 'exec')
PY
install -d -o root -g root -m 755 /opt/cruza-comms-health
install -d -o ebach -g ebach -m 700 /home/ebach/cruza-comms-health
install -o root -g root -m 644 "$source_dir/comms-health.py" "$source_dir/flight-health.py" /opt/cruza-comms-health/
install -o root -g root -m 644 "$source_dir/cruza-comms-health.service" /etc/systemd/system/cruza-comms-health.service
systemd-analyze verify /etc/systemd/system/cruza-comms-health.service
systemctl daemon-reload
systemctl enable cruza-comms-health.service
systemctl restart cruza-comms-health.service
systemctl status cruza-comms-health.service --no-pager
