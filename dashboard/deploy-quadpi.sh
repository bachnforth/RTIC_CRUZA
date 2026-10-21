#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID -eq 0 ]] || exit 1
expected=8f6319d5ea43bd54a480042a7873374ec60c1eecec44e33af1d16a830cb276de
[[ $(sha256sum /usr/local/bin/picam-stream.sh | cut -d' ' -f1) == "$expected" ]] || { echo 'quadpi video code changed since audit; refusing overwrite'; exit 1; }
backup=/var/backups/quadpi/video-dashboard-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 700 "$backup"
cp -a /usr/local/bin/picam-stream.sh /etc/default/picam-stream "$backup/"
[[ ! -e /opt/cruza-video-tap.py ]] || cp -a /opt/cruza-video-tap.py "$backup/"
bash -n picam-stream.sh
python3 -m py_compile video-tap.py
install -m 755 picam-stream.sh /usr/local/bin/picam-stream.sh
install -m 644 video-tap.py /opt/cruza-video-tap.py
printf '\n# Optional loopback copy; existing QGC destination remains unchanged.\nDASHBOARD_MIRROR_PORT="15601"\n' >> /etc/default/picam-stream
systemctl restart picam-stream.service
echo "quadpi backup: $backup"
systemctl is-active picam-stream.service
