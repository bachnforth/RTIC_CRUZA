#!/bin/bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run with sudo on the Pi.' >&2; exit 1; }
[[ ${1:-} == cruza || ${1:-} == quadpi ]] || { echo 'Usage: install-path-health.sh cruza|quadpi' >&2; exit 1; }
source_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
id ebach >/dev/null
python3 - "$source_dir" "$1" <<'PY'
import importlib.util, json, sys
from pathlib import Path
root = Path(sys.argv[1])
for name in ('path-health.py', 'comms-health.py', 'flight-health.py'):
    compile((root/name).read_text(), name, 'exec')
spec = importlib.util.spec_from_file_location('path_health', root/'path-health.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate(json.loads((root/f'path-health.{sys.argv[2]}.json').read_text()))
PY
backup="/var/backups/cruza-path-health/$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 700 "$backup"
for existing in /opt/cruza-path-health /etc/cruza-path-health.json /etc/systemd/system/cruza-path-health.service; do
    [[ ! -e "$existing" ]] || cp -a "$existing" "$backup/"
done
install -d -o root -g root -m 755 /opt/cruza-path-health
install -d -o ebach -g ebach -m 700 /home/ebach/cruza-path-health
install -o root -g root -m 644 "$source_dir/path-health.py" "$source_dir/comms-health.py" "$source_dir/flight-health.py" /opt/cruza-path-health/
# Keep local target choices across updates. Edit the reviewed JSON before first installation.
if [[ ! -e /etc/cruza-path-health.json ]]; then
    install -o root -g root -m 644 "$source_dir/path-health.$1.json" /etc/cruza-path-health.json
fi
install -o root -g root -m 644 "$source_dir/cruza-path-health.service" /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/cruza-path-health.service
systemctl daemon-reload
systemctl enable cruza-path-health.service
systemctl restart cruza-path-health.service
echo "Backup: $backup"
systemctl status cruza-path-health.service --no-pager
