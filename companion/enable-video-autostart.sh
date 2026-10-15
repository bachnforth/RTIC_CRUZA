#!/bin/bash
# Opt-in deployment for continuous video; no flight-controller changes or reboot.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash enable-video-autostart.sh'; exit 1; }
cd -- "$(dirname -- "$0")"
source_dir=$PWD
backup=/var/backups/cruza/video-autostart-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 700 "$backup"
cp -a /opt/cruza/cruza.py "$backup/cruza.py"
cp -a /etc/cruza/config.json "$backup/config.json"
cp -a /etc/systemd/system/cruza-video.service "$backup/cruza-video.service"
systemctl is-enabled cruza-video > "$backup/enabled-state.txt" || true
systemctl is-active cruza-video > "$backup/active-state.txt" || true
python3 - "$backup/config.json" "$backup/new-config.json" <<'PY'
import json,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text())
c['video_max_seconds']=0
Path(sys.argv[2]).write_text(json.dumps(c,indent=2)+'\n')
PY
python3 "$source_dir/cruza.py" validate --config "$backup/new-config.json"
systemd-analyze verify "$source_dir/systemd/cruza-video.service"
rollback() {
    trap - ERR
    echo "Deployment failed; restoring $backup" >&2
    systemctl stop cruza-video || true
    cp -a "$backup/cruza.py" /opt/cruza/cruza.py
    cp -a "$backup/config.json" /etc/cruza/config.json
    cp -a "$backup/cruza-video.service" /etc/systemd/system/cruza-video.service
    systemctl daemon-reload
    if grep -qx enabled "$backup/enabled-state.txt"; then
        systemctl enable cruza-video
    else
        systemctl disable cruza-video || true
    fi
    if grep -qx active "$backup/active-state.txt"; then systemctl start cruza-video; fi
}
trap rollback ERR
systemctl stop cruza-video
install -m 755 "$source_dir/cruza.py" /opt/cruza/cruza.py
install -m 644 "$source_dir/systemd/cruza-video.service" /etc/systemd/system/cruza-video.service
install -m 644 "$backup/new-config.json" /etc/cruza/config.json
systemctl daemon-reload
if systemctl is-failed --quiet cruza-video; then
    systemctl reset-failed cruza-video
fi
systemctl enable --now cruza-video
sleep 5
systemctl is-active --quiet cruza-video
trap - ERR
echo "Video enabled at boot with no session timeout. Backup: $backup"
echo 'Video uses the existing configured destination, bitrate and port, even when QGC is closed.'
echo 'No reboot, flight-controller changes or MAVLink-router restart performed.'
