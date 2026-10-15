#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID -eq 0 ]] || exit 1
expected=f773ef403243527b2f9d4c46c2d25214f797539ddf5fec8a1beb9bd697a74b20
[[ $(sha256sum /opt/cruza/cruza.py | cut -d' ' -f1) == "$expected" ]] || { echo 'Cruza code changed since audit; refusing overwrite'; exit 1; }
backup=/var/backups/cruza/video-dashboard-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 700 "$backup"
cp -a /opt/cruza/cruza.py /etc/cruza/config.json "$backup/"
[[ ! -e /opt/cruza-video-tap.py ]] || cp -a /opt/cruza-video-tap.py "$backup/"
python3 -m py_compile cruza.py video-tap.py
install -m 644 cruza.py /opt/cruza/cruza.py
install -m 644 video-tap.py /opt/cruza-video-tap.py
python3 - <<'PY'
import json, os
from pathlib import Path
p=Path('/etc/cruza/config.json')
c=json.loads(p.read_text())
c['video_mirror_port']=15600
q=p.with_suffix('.dashboard.tmp')
q.write_text(json.dumps(c,indent=2)+'\n')
q.chmod(0o644)
os.replace(q,p)
PY
if ! python3 /opt/cruza/cruza.py validate; then
    cp -a "$backup/cruza.py" /opt/cruza/cruza.py
    cp -a "$backup/config.json" /etc/cruza/config.json
    exit 1
fi
systemctl restart cruza-video.service
echo "Cruza backup: $backup"
systemctl is-active cruza-video.service cruza-router.service
