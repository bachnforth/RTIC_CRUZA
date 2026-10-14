#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
mmcli -L
echo 'Inspect the detected modem with mmcli -m INDEX before running this script with --create.'
[[ ${1:-} == --create ]] || exit 0
# Do not guess or switch USB mode and do not replace existing connection profiles.
if nmcli -g NAME connection show | grep -qx cruza-lte; then
    echo 'cruza-lte exists; preserve it and inspect with nmcli connection show cruza-lte.'
    exit 0
fi
mmcli -L | grep -q '/Modem/' || { echo 'No modem detected; check power and USB data path'; exit 1; }
nmcli connection add type gsm ifname '*' con-name cruza-lte apn america.bics
nmcli connection modify cruza-lte connection.autoconnect yes connection.autoconnect-retries 0 \
    ipv4.route-metric 700 ipv6.route-metric 700
nmcli --wait 60 connection up cruza-lte
interface=$(nmcli -g GENERAL.IP-IFACE device show cdc-wdm0)
python3 - "$interface" <<'PY'
from pathlib import Path
import datetime, json, re, shutil, sys
interface = sys.argv[1].strip()
if not re.fullmatch(r'[\w.-]+', interface) or not (Path('/sys/class/net') / interface).exists():
    raise SystemExit('Cannot identify LTE data interface; inspect nmcli before configuring usage monitoring')
p = Path('/etc/cruza/config.json')
backup = Path('/var/backups/cruza') / ('lte-interface-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True, mode=0o700, exist_ok=False)
shutil.copy2(p, backup / 'config.json')
c = json.loads(p.read_text())
c['lte_interface'] = interface
tmp = p.with_suffix('.tmp')
tmp.write_text(json.dumps(c, indent=2) + '\n')
tmp.chmod(0o644)
tmp.replace(p)
print('LTE usage interface configured:', interface)
PY
echo 'Wi-Fi stays preferred on the bench. Verify LTE-bound ping/HTTPS before declaring cellular internet working.'
