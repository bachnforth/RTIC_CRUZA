#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run once with sudo bash install-powerdown.sh' >&2; exit 1; }
cd -- "$(dirname -- "$0")"
/usr/bin/id ebach >/dev/null
/usr/bin/bash -n shutdown.sh
for parent in /usr/local/sbin /etc/sudoers.d; do
    [[ -d $parent ]] || /usr/bin/install -d -o root -g root -m 755 "$parent"
    [[ $(/usr/bin/stat -c %u "$parent") == 0 ]] || { echo "Unsafe owner: $parent" >&2; exit 1; }
    mode=$(/usr/bin/stat -c %a "$parent")
    (( (8#$mode & 022) == 0 )) || { echo "Unsafe write permissions: $parent" >&2; exit 1; }
done
rule=/etc/sudoers.d/cruza-powerdown
helper=/usr/local/sbin/cruza-powerdown
stamp=$(/usr/bin/date -u +%Y%m%dT%H%M%SZ)
backup=/var/backups/cruza/powerdown-$stamp
/usr/bin/install -d -o root -g root -m 700 "$backup"
[[ ! -e $rule ]] || /usr/bin/cp -a "$rule" "$backup/sudoers"
[[ ! -e $helper ]] || /usr/bin/cp -a "$helper" "$backup/helper"
candidate=$(/usr/bin/mktemp /etc/sudoers.d/.cruza-powerdown.XXXXXX)
trap '/usr/bin/rm -f -- "$candidate"' EXIT
printf '%s\n' 'ebach ALL=(root) NOPASSWD: /usr/local/sbin/cruza-powerdown ""' > "$candidate"
/usr/bin/chmod 440 "$candidate"
/usr/sbin/visudo -cf "$candidate"
# Install a root-owned copy. Never authorize the user-writable home-directory script.
/usr/bin/install -o root -g root -m 755 shutdown.sh "$helper"
/usr/bin/install -o root -g root -m 440 "$candidate" "$rule"
if ! /usr/sbin/visudo -c; then
    if [[ -e $backup/sudoers ]]; then
        /usr/bin/cp -a "$backup/sudoers" "$rule"
    else
        /usr/bin/rm -f -- "$rule"
    fi
    echo "Sudo configuration invalid; permission change rolled back. Backup: $backup" >&2
    exit 1
fi
echo 'Password-free guarded shutdown installed: sudo -n /usr/local/sbin/cruza-powerdown'
echo "Backup: $backup"
