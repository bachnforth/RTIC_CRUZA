#!/bin/bash
# Bounded bench diagnostic using the existing router/config, with restoration.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
systemctl is-active --quiet cruza-router.service
test -s /run/cruza/router.conf
debug_config=$(mktemp /run/cruza-router-debug.XXXXXX)
cp /run/cruza/router.conf "$debug_config"
unit="cruza-router-debug-restore-$(date +%s)"
systemd-run --unit="$unit" --on-active=25s /usr/bin/systemctl start cruza-router.service
systemctl is-active --quiet "$unit.timer"
trap 'systemctl start cruza-router.service; rm -f -- "$debug_config"' EXIT
systemctl stop cruza-router.service
set +e
timeout --signal=TERM --kill-after=2s 8s /usr/local/bin/mavlink-routerd -t 0 -v -c "$debug_config"
result=$?
set -e
[[ $result == 0 || $result == 124 ]] || exit "$result"
