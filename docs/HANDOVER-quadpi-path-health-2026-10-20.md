# Handover: 10-inch QuadPi connectivity logger

Prepared October 20, 2026. This package adds independent connectivity evidence
on the 10-inch quad's Raspberry Pi. QuadPi installation and live testing are
pending; the aircraft was not powered during preparation.

## Architecture and current status

The workspace's cooperative communications path is:

```text
Cruza Pi -- LTE / Headscale VPN --> laptop application gateway
                                      |
                                   mesh radio
                                      |
                                   QuadPi
```

The logger follows that path: Cruza monitors the gateway over VPN; QuadPi
monitors the gateway over mesh. It does not create a direct mesh link from
Cruza, change routes, or enable the optional observation transport.

Cruza installation was verified October 20 at approximately 10:08 CDT:

- `cruza-path-health.service` enabled, active/running, exit status 0, zero restarts.
- Gateway `100.100.0.23` reachable through `tailscale0`; latest RTT 125 ms.
- Packet observer `udp.error=null`; CAP_NET_RAW present.
- Existing router, video and original communications logger active.
- Observation publisher remains disabled/inactive in standalone mode.
- Boot enablement is configured; a subsequent cold boot has not been tested.

Observation forwarding is not commissioned. Its existing configuration is
disabled and incomplete, so endpoint ping results must not be presented as
successful end-to-end observation delivery.

## Files in this package

Keep these files together:

| File | Purpose |
|---|---|
| `path-health.py` | New hop connectivity logger and JSON summary command |
| `comms-health.py`, `flight-health.py` | Required shared modules; imported only, their main loops are not started |
| `path-health.quadpi.json` | QuadPi target/source addresses and service names |
| `cruza-path-health.service` | Shared service name used on either Pi |
| `install-path-health.sh` | Root-owned installation, backup and boot enablement |
| `test_path_health.py`, `test_comms_health.py`, `test_flight_health.py` | Twelve offline checks |
| `README.md` | This handover |

The package contains no SSH private keys, passwords or observation authentication
keys. Use an existing authorized connection to QuadPi.

## 1. Verify addresses and existing logging

The staged profile contains:

```json
{
  "node": "quadpi",
  "targets": [
    {
      "name": "gateway-mesh",
      "source_ip": "10.223.79.20",
      "peer_ip": "10.223.58.11",
      "network": "10.223.0.0/16"
    }
  ],
  "services": ["picam-stream", "mesh-logger", "safety-mavlink-filter"]
}
```

`10.223.79.20` is QuadPi's recorded mesh IP; it needs live confirmation.
`10.223.58.11` was the current gateway laptop's Wi-Fi 2 mesh address on
October 20. If using RN20 over USB, another laptop, or another mesh-side
address, replace `peer_ip` with the actual application gateway's address.
The radio management IP is not a substitute for the laptop gateway IP.

The selected radio roles are RN20 at GCS, RN08 with QuadPi, and RN03 replacing
the Mini in its intended aircraft role. Physical deployment and effective
routes still need live confirmation. Preserve the established network setup.

Run on QuadPi, after connecting by SSH:

```bash
hostname
ip -br -4 address
ip route get 10.223.58.11 from 10.223.79.20
systemctl status mesh-logger.service --no-pager
systemctl cat mesh-logger.service
systemctl is-active picam-stream.service safety-mavlink-filter.service
```

Substitute confirmed addresses in all commands. Inspect the existing logger
before installation: the sibling Quad project has an older `mesh_logger.py`
that can record radio RSSI/SNR/retries and optional FC telemetry. Its installed
state has not been checked. This new service can supplement it; the installer
does not stop or replace it. Confirm combined CPU/storage use if both run.
Remove or correct service names in the profile if they do not exist on QuadPi.

## 2. Transfer and install

Extract the ZIP and copy its contents to
`/home/ebach/companion/path-health/` on QuadPi using your existing SSH/SCP
connection. Example from Windows PowerShell, with the package extracted to
the current folder and QuadPi reachable at its confirmed mesh IP:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" ebach@10.223.79.20 "mkdir -p /home/ebach/companion/path-health"
scp -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" .\*.py .\*.json .\*.service .\*.sh .\README.md ebach@10.223.79.20:/home/ebach/companion/path-health/
ssh -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" ebach@10.223.79.20
```

Use your own authorized key/path if different. Then, **inside the QuadPi SSH
session**, run:

```bash
cd /home/ebach/companion/path-health
nano path-health.quadpi.json
python3 -m unittest discover -p 'test_*health.py' -v
bash -n install-path-health.sh
sudo bash install-path-health.sh quadpi
```

The installer assumes Linux, Python 3, systemd and an existing `ebach` user/group.
Diagnostics use `ip`, `ping`, `systemctl`, `timedatectl` and `vcgencmd`; no pip
packages are needed. Sudo uses the Pi owner's password. Do not run the sudo
command in Windows PowerShell.

The installer backs up existing path-logger files to
`/var/backups/cruza-path-health/TIMESTAMP-PID/`, installs code under
`/opt/cruza-path-health/`, configuration at `/etc/cruza-path-health.json`, and
enables/starts only `cruza-path-health.service`.

On updates, an existing `/etc/cruza-path-health.json` is preserved. Edit that
installed file with sudo and restart only `cruza-path-health.service` if
changing targets after first installation. Editing the staged profile alone
does not change the running configuration on subsequent installs.

## 3. Verify

```bash
systemctl is-enabled cruza-path-health.service
systemctl show cruza-path-health.service -p ActiveState -p SubState -p NRestarts -p ExecMainStatus
journalctl -u cruza-path-health.service -n 10 --no-pager
ls -lt /home/ebach/cruza-path-health/
```

Wait at least 20 seconds, identify the newly created session file, then inspect
its last sample with `tail -n 1 EXACT_FILE`. Confirm:

- `node=quadpi`, target `gateway-mesh`, correct mesh interface and source config.
- Samples grow roughly every 10 seconds; `state=reachable`, RTT populated.
- `udp.error=null`; packet counters appear when peer traffic is present.
- Existing video, telemetry and any older mesh logger remain in their prior state.

`unavailable/source_address_absent` means the configured local address is not
assigned. `unavailable/route_missing_or_wrong_interface` means the selected
route is missing or uses a different interface; this prevents claiming mesh
success via an unintended VPN path. `no_reply` means an attempted ping got no
reply and can also result from ICMP filtering. Passive-capture permission
errors should clear under the installed capability-bearing unit.

When convenient, check persistence after a normal power cycle. Boot startup
has not yet been verified on QuadPi.

## 4. Logs and reports

Output: `/home/ebach/cruza-path-health/comms-SESSION-00001.jsonl` and subsequent
segments. Defaults are approximately 4 MiB/segment, 128 MiB aggregate retention,
and a 256 MiB free-space reserve. Old matching segments are removed by retention;
copy relevant sessions promptly. The separate original Cruza LTE logger keeps
its existing output directory.

Each sample records source-route checks, one source-bound probe, RTT,
reachability transitions, interface status/counters, selected service states,
temperature/throttling/load, UTC, monotonic time, boot ID and session ID.
Passive traffic records only fixed metadata categories and gap/age counters.
No packet payload, object position or GPS data is retained by this logger.

Generate a summary on either a Pi or Python-equipped laptop:

```bash
python3 /opt/cruza-path-health/path-health.py --report /home/ebach/cruza-path-health/EXACT_SESSION_FILE.jsonl
```

For a split session, pass every relevant segment once. The report groups
retained samples by session and gives reachable/no-reply/unavailable counts,
mean RTT and latest observed state. An interrupted final JSON line is skipped.
Counters reset across boots/interfaces; monotonic times are comparable only
within the appropriate boot/session. Observed state durations have roughly
10-second sampling resolution, and shorter outages can be missed.

To stop this new logger only:

```bash
sudo systemctl disable --now cruza-path-health.service
```

## Return evidence / remaining commissioning

Please return the verified QuadPi and gateway mesh IPs, route output, existing
logger details, service status, a 30–60 second sample session, and whether normal
boot startup was verified. Note any clock mismatch or unavailable diagnostics.

With both Pis logging, compare Cruza→gateway VPN evidence with QuadPi→gateway
mesh evidence. Full application delivery requires gateway/receiver counters
and authenticated observation ACKs. Persistent gateway-side logging and actual
cooperative forwarding commissioning remain outstanding. No test observation
should be treated as a flight command or proof of video reception/display.
