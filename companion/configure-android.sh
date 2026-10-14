#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash configure-android.sh ANDROID_TAILNET_IP'; exit 1; }
python3 - "$1" <<'PY'
import datetime, json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, '/opt/cruza')
from cruza import config, tail_ip
peer = tail_ip(sys.argv[1])
p = Path('/etc/cruza/config.json')
c = config(p)
if Path('/etc/cruza/firewall.nft').exists() and c['android_ip'] != peer:
    raise SystemExit('Firewall already configured for a different peer; review it before changing the address')
backup = Path('/var/backups/cruza') / ('peer-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True, mode=0o700, exist_ok=False)
shutil.copy2(p, backup / 'config.json')
c['android_ip'] = peer
tmp = p.with_suffix('.tmp')
tmp.write_text(json.dumps(c, indent=2) + '\n')
os.chmod(tmp, 0o644)
tmp.replace(p)
print('Android peer configured:', peer, 'Backup:', backup)
PY
