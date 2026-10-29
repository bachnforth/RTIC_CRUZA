#!/bin/bash
# Staged install of the Cruza observation detector on the Pi. Run by the owner
# as root, locally. It installs the camera-only detector and its loopback tap,
# installs the systemd unit WITHOUT enabling it, and merges a default observe
# config block if none exists. It changes no flight-controller, routing, video,
# firewall or modem configuration. Enabling the service is a separate, deliberate
# opt-in step (printed at the end). Back up and rollback instructions included.
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID -eq 0 ]] || { echo 'Run as root (sudo bash deploy-observe.sh)'; exit 1; }

# cruza-stream (video + detections from one camera) supersedes this detector and
# owns the IMX500; two processes cannot. Installing this one alongside it is the
# boot race that cost video and detections on 28 Oct 2026.
if systemctl is-enabled --quiet cruza-stream.service 2>/dev/null \
   || systemctl is-active --quiet cruza-stream.service 2>/dev/null; then
    echo 'cruza-stream is enabled or running: it already publishes detections from'
    echo 'the same camera, with video. Only one process can own the IMX500.'
    echo 'To go back to the separate detector, first:'
    echo '    sudo systemctl disable --now cruza-stream.service'
    exit 1
fi

# The unit file is the single source of truth for the account the detector runs
# as: the reflashed image has no 'ebach'. Override with CRUZA_USER=... if needed.
cruza_user=${CRUZA_USER:-$(sed -n 's/^User=//p' systemd/cruza-observe.service | head -1)}
id -u "$cruza_user" >/dev/null 2>&1 || {
    echo "No such user: ${cruza_user:-(none)}. Set CRUZA_USER=<account> and rerun."; exit 1; }

# Fail early if the IMX500 stack is not ready, so we never install a detector
# that cannot run. This checks only; it installs no packages and changes nothing.
model=/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk
if [[ ! -e "$model" ]]; then
    echo "IMX500 model missing: $model"
    echo "Install the firmware first:  sudo apt install imx500-all python3-picamera2"
    exit 1
fi
if ! sudo -u "$cruza_user" python3 -c 'from picamera2 import Picamera2; from picamera2.devices import IMX500' 2>/dev/null; then
    echo "picamera2 / IMX500 Python support not available for user $cruza_user."
    echo 'Install:  sudo apt install python3-picamera2'
    exit 1
fi

python3 -m py_compile observe.py observe-tap.py

backup=/var/backups/cruza/observe-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 700 "$backup"
[[ ! -e /opt/cruza/observe.py ]]     || cp -a /opt/cruza/observe.py "$backup/"
[[ ! -e /opt/cruza-observe-tap.py ]] || cp -a /opt/cruza-observe-tap.py "$backup/"
[[ ! -e /etc/systemd/system/cruza-observe.service ]] || \
    cp -a /etc/systemd/system/cruza-observe.service "$backup/"
cp -a /etc/cruza/config.json "$backup/"

install -m 644 observe.py /opt/cruza/observe.py
install -m 644 observe-tap.py /opt/cruza-observe-tap.py
install -m 644 systemd/cruza-observe.service /etc/systemd/system/cruza-observe.service

# Add the default observe block only if the config has none; never overwrite
# values the owner has already tuned.
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path('/etc/cruza/config.json')
c = json.loads(p.read_text())
if 'observe' not in c:
    c['observe'] = {
        "model": "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk",
        "loopback_port": 15620, "min_score": 0.55, "max_rate_hz": 5,
        "repeat_seconds": 3.0, "hfov_deg": 66.0, "vfov_deg": 49.0,
        "classes": ["person", "bicycle", "car", "motorcycle", "bus", "truck", "boat", "airplane"],
    }
    q = p.with_suffix('.observe.tmp')
    q.write_text(json.dumps(c, indent=2) + '\n')
    q.chmod(0o644)
    os.replace(q, p)
    print('Added default observe config block.')
else:
    print('Existing observe config kept.')
PY

# Validate the config loads (no camera opened, no records sent).
sudo -u "$cruza_user" python3 /opt/cruza/observe.py --synthetic 0

systemctl daemon-reload
echo
echo "Installed. Backup: $backup"
echo "The detector is NOT enabled. Review the camera field-of-view and mount"
echo "angles, then enable it as a deliberate step:"
echo "    sudo systemctl enable --now cruza-observe.service"
echo "This unit conflicts with cruza-stream: enabling it stops that service and"
echo "gives up the combined video + detection stream. Enable only one of them."
echo "Watch it:        journalctl -fu cruza-observe"
echo "Bench self-test: sudo -u $cruza_user python3 /opt/cruza/observe.py --synthetic 8"
echo
echo "Rollback:"
echo "    sudo systemctl disable --now cruza-observe.service"
echo "    sudo rm /etc/systemd/system/cruza-observe.service /opt/cruza-observe-tap.py"
echo "    sudo cp -a $backup/config.json /etc/cruza/config.json   # if desired"
echo "    sudo systemctl daemon-reload"
echo "No flight, routing, video or firewall configuration was changed."
