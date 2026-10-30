#!/bin/sh
# Adds a source network to the echo's accept list and restarts the service.
#
# Run ON the drone:  sh ~/linktest/tfwdrone/allow-source.sh <CIDR>
#   e.g.             sh ~/linktest/tfwdrone/allow-source.sh 10.223.53.10/32
#
# The echo accepts probes only from plan.cruza.tailnet_ip plus
# cruza.extra_allow. Use this when the Cruza's packets reach the drone with a
# different source address than its VPN one -- e.g. relayed by the mesh gateway.
set -eu

[ $# -eq 1 ] || { echo "usage: $0 <CIDR, e.g. 10.223.53.10/32>" >&2; exit 2; }
CIDR=$1
cd "$HOME/linktest"

python3 - "$CIDR" <<'PY'
import ipaddress, json, pathlib, shutil, sys, time

cidr = sys.argv[1]
ipaddress.ip_network(cidr, strict=False)   # reject a malformed argument outright

p = pathlib.Path("plan.json")
plan = json.loads(p.read_text(encoding="utf-8-sig"))
backup = p.with_name("plan.backup-%d.json" % time.time_ns())
shutil.copy2(p, backup)

allowed = plan["cruza"].setdefault("extra_allow", [])
if cidr in allowed:
    print("already present:", cidr)
else:
    allowed.append(cidr)
    p.write_text(json.dumps(plan, indent=2) + "\n")
    print("added:", cidr)
print("accept list is now:", [plan["cruza"]["tailnet_ip"] + "/32"] + allowed)
print("backup:", backup.name)
PY

# The echo is managed by systemd (Restart=always), so a hand-started copy holds
# ~/linktest-logs/echo.pid and UDP 15700, and the service then crash-loops with
# "A linktest echo is already running". Clear one if it is there.
if pid=$(cat "$HOME/linktest-logs/echo.pid" 2>/dev/null)    && [ -n "$pid" ]    && [ "$pid" != "$(systemctl show -p MainPID --value linktest-echo)" ]; then
    echo "stopping a hand-started echo (pid $pid) so the service can own the port"
    python3 linktest.py stop --role echo || true
    sleep 2
fi

sudo systemctl reset-failed linktest-echo || true
sudo systemctl restart linktest-echo
sleep 8

echo "--- service ---"
# '|| true': is-active exits non-zero while 'activating', which set -e would take
# as a failure.
systemctl is-active linktest-echo || true
echo "--- the new session's accept list ---"
d=$(ls -dt "$HOME"/linktest-logs/*_echo_* | head -1)
echo "session: $(basename "$d")"
grep -m1 '"k":"meta"' "$d/events-0001.jsonl" 2>/dev/null \
  || sed -n 's/.*\("allowed":[^]]*]\).*/\1/p' "$d/status.json" 2>/dev/null \
  || echo "(meta not flushed yet; check again in a minute)"
echo "--- recent log ---"
journalctl -u linktest-echo -n 3 --no-pager
