#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/var/backups/cruza/uart-$stamp
install -d -m 700 "$backup"
cp -a /boot/firmware/config.txt /boot/firmware/cmdline.txt "$backup/"
python3 - <<'PY'
from pathlib import Path
p = Path('/boot/firmware/cmdline.txt')
tokens = p.read_text().split()
p.write_text(' '.join(t for t in tokens if not t.startswith(('console=serial0,','console=ttyAMA0,','console=ttyS0,'))) + '\n')
p = Path('/boot/firmware/config.txt')
text = p.read_text()
if '# Cruza GPIO UART' not in text:
    p.write_text(text + '\n[all]\n# Cruza GPIO UART\nenable_uart=1\ndtoverlay=disable-bt\n')
PY
systemctl disable hciuart.service || true
systemctl disable serial-getty@ttyAMA0.service serial-getty@ttyS0.service || true
echo "Pi reboot required. UART backup: $backup. Bluetooth will be disabled after reboot; Wi-Fi remains enabled."
