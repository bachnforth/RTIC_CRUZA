#!/bin/bash
set -euo pipefail
[[ $# -eq 0 ]] || { echo 'This command accepts no arguments.' >&2; exit 1; }
if /usr/bin/systemctl is-active --quiet cruza-install.service; then
    echo 'Shutdown refused: Cruza installation is running. Wait for it to finish.' >&2
    exit 1
fi
if /usr/bin/pgrep -x 'apt|apt-get|dpkg|ninja' >/dev/null; then
    echo 'Shutdown refused: package installation or a build is running.' >&2
    exit 1
fi
[[ $EUID -eq 0 ]] || { echo 'Run with sudo after the installer has finished.' >&2; exit 1; }
exec /usr/sbin/shutdown -h now
