#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[[ $EUID -eq 0 ]] || { echo 'Run with sudo bash install.sh'; exit 1; }
exec 9>/run/lock/cruza-install.lock
flock -n 9 || { echo 'Another Cruza installer is running'; exit 1; }
source /etc/os-release
# Raspberry Pi OS Trixie: 32-bit reports ID=raspbian, 64-bit reports ID=debian.
[[ ( ${ID:-} == raspbian || ${ID:-} == debian ) && ${VERSION_CODENAME:-} == trixie ]] || { echo 'Installer audited for Raspberry Pi OS (Raspbian/Debian) Trixie only'; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/var/backups/cruza/$stamp
install -d -m 700 "$backup"
for p in /etc/cruza /opt/cruza /etc/systemd/system/cruza-*; do
    [[ -e $p ]] && cp -a --parents "$p" "$backup/"
done
apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 update
apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 install -y --no-install-recommends modemmanager curl ca-certificates nftables \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad git meson ninja-build pkg-config g++ libsystemd-dev
# Official signed Tailscale apt repository; no credentials stored in source.
if ! command -v tailscale >/dev/null; then
    curl --fail --location --retry 3 "https://pkgs.tailscale.com/stable/${ID}/trixie.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
    curl --fail --location --retry 3 "https://pkgs.tailscale.com/stable/${ID}/trixie.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
    apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 update
    apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=3 install -y tailscale
fi
if ! command -v mavlink-routerd >/dev/null; then
    # Build the upstream v4 release; record exact commit and package versions.
    build=$(mktemp -d /var/tmp/cruza-router.XXXXXX)
    git clone --depth 1 --branch v4 --recurse-submodules --shallow-submodules https://github.com/mavlink-router/mavlink-router.git "$build/source"
    meson setup "$build/build" "$build/source" --prefix=/usr/local -Dsystemdsystemunitdir=/var/tmp/cruza-unused-units
    ninja -C "$build/build" -j1
    install -m 755 "$build/build/src/mavlink-routerd" /usr/local/bin/mavlink-routerd
    git -C "$build/source" rev-parse HEAD > "$backup/router-commit.txt"
fi
install -d /opt/cruza /etc/cruza /var/lib/cruza
install -m 755 cruza.py /opt/cruza/cruza.py
if [[ ! -e /etc/cruza/config.json ]]; then
    install -m 644 config.example.json /etc/cruza/config.json
fi
install -m 644 systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ModemManager tailscaled cruza-usage.timer cruza-lte-health.timer
bash ./install-powerdown.sh
dpkg-query -W > "$backup/packages.tsv"
python3 /opt/cruza/cruza.py validate
echo "Installed. Backup: $backup. Router/video remain disabled until bench configuration."
echo 'Next: sudo tailscale up; configure GPIO UART using configure-uart.sh; set Android tailnet IP in /etc/cruza/config.json.'
