#!/bin/sh
# Installs the linktest echo as a boot service on TFWDRONE.
#
# Run ON the drone:  sh ~/linktest/tfwdrone/install-echo-autostart.sh
# Remove after the test:  sudo systemctl disable --now linktest-echo
#
# Idempotent: re-running replaces the unit and restarts the service.
set -eu

NAME=tfwdrone
ACCT=$(id -un)
HOME_DIR=$(getent passwd "$ACCT" | cut -d: -f6)
TOOL="$HOME_DIR/linktest/linktest.py"
PY=$(command -v python3)

[ -f "$TOOL" ] || { echo "ERROR: $TOOL not found. Copy linktest.py and plan.json to ~/linktest/ first." >&2; exit 1; }
[ -n "$PY" ] || { echo "ERROR: python3 not on PATH." >&2; exit 1; }
"$PY" "$TOOL" --version >/dev/null || { echo "ERROR: $TOOL will not run." >&2; exit 1; }

mkdir -p "$HOME_DIR/linktest-logs"

# --duration 14400 is the tool's maximum; the echo adds 15 min and then exits
# cleanly, so Restart=always opens a fresh session. The report stitches
# consecutive sessions together.
sudo tee /etc/systemd/system/linktest-echo.service >/dev/null <<UNIT
[Unit]
Description=linktest echo for $NAME (Cruza -> quad data-link test)
Documentation=file://$HOME_DIR/linktest/tfwdrone/HANDOVER-tfwdrone-echo.md
After=network.target

[Service]
Type=simple
User=$ACCT
WorkingDirectory=$HOME_DIR/linktest
# This Pi has no RTC, so at boot the clock is wrong until NTP lands. The report
# time-matches this log against the Cruza's flight log, so a skewed clock
# silently misplaces probes. Wait up to 120 s for a synchronised clock, then
# start regardless -- missing the test entirely would be worse than a skew.
ExecStartPre=/bin/sh -c 'for i in \$(seq 1 60); do [ "\$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] && exit 0; sleep 2; done; exit 0'
TimeoutStartSec=180
ExecStart=$PY $TOOL echo --name $NAME --duration 14400
Nice=5
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable linktest-echo
# restart, not 'enable --now': --now leaves an already-running instance on the
# old unit file, so re-running this script would not apply a change.
sudo systemctl restart linktest-echo
sleep 5

echo "--- unit state ---"
systemctl is-enabled linktest-echo
systemctl is-active linktest-echo
echo "--- listening ---"
ss -lun | grep 15700 || echo "WARNING: nothing listening on UDP 15700"
echo "--- recent log ---"
journalctl -u linktest-echo -n 5 --no-pager
