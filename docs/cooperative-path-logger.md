# Cooperative path connectivity evidence

The established path is Cruza → LTE/Headscale VPN → laptop application gateway
→ mesh radio → QuadPi. A direct Cruza-to-QuadPi mesh route is not assumed or added.
The existing Cruza communications logger continues recording LTE, phone/QGC,
video and local resources. The separate `companion/path-health.py` records each
Pi's connection to the gateway without enabling observation sharing.

## Targets

- Cruza: source VPN address `100.100.0.58`, gateway `100.100.0.23`.
  Both were observed live on October 20, 2026.
- QuadPi staged profile: recorded mesh address `10.223.79.20`, gateway
  `10.223.58.11`. The laptop address was observed live on Wi-Fi 2 on October 20.
  QuadPi was powered off according to the owner and is not yet verified.
  RN20 USB GCS deployment may change the laptop's mesh address/interface;
  verify and edit the target profile before QuadPi installation.

Each target declares its source address and allowed subnet. A sample resolves
the current interface owning that source and checks the destination route uses
that interface before sending one source-bound ICMP probe. Missing source or a
different selected route produces `unavailable`, never a successful fallback
through another link. Probe return code 1 is `no_reply`; execution errors are
`unavailable`. Neither missing configuration nor a local execution error is
reported as measured network packet loss. No routes or interfaces are changed.

## Recorded evidence and limits

Samples target a 10-second cadence. Up to four probes and bounded diagnostic
commands can extend it. Samples record UTC, monotonic time, session and boot ID,
probe result/RTT, reachability transitions, interface ifindex/status/counters,
configured service states/restarts, temperature, throttling, load and time sync.
Interpret counter deltas within a boot/interface epoch. UTC can step after boot;
use monotonic times within a session. Transition durations describe observed
states, not precise physical outage boundaries. Sub-interval outages can be missed.

With CAP_NET_RAW, a retrying packet observer records cumulative IPv4 packet/byte
counts by direction and ICMP/TCP/UDP, plus fixed UDP port categories for video
(5600), MAVLink (14550/14560) and observation transport (17841/17842), with
last-seen ages and maximum gaps. These are metadata only: no payloads, GPS,
object locations or credentials are saved. Packets may count in both their
protocol and application-port category; do not add those categories together.
Ports are classification hints, not authenticated application acknowledgments.
Missing permissions are explicit in `udp.error`; reachability still records.

The logger reuses the existing 4 MiB segments, 128 MiB aggregate retention,
256 MiB free-space reserve and fsync behavior. Its own directory is separate
from existing Cruza logs. Low disk skips samples. Storage retention can remove
old evidence, and a power interruption may truncate the last record.

Ping success and packet transmission do not establish accepted observation
delivery or display. Gateway and receiver application counters/authenticated
ACKs are needed for end-to-end delivery claims. The publisher is currently
disabled in standalone mode, with destination unset. This logger does not change
that state or bypass the existing cooperative commissioning requirements.
The laptop gateway also needs its own persistent evidence when commissioned;
neither Pi can explain every gateway-side failure by itself.

## Install

Cruza staging directory: `/home/ebach/companion/path-health/`.
After reviewing targets, run on Cruza in the owner's terminal:

```bash
sudo bash /home/ebach/companion/path-health/install-path-health.sh cruza
```

The installer requires the owner's sudo password, backs up existing path-logger
files, installs root-owned code/config and enables only
`cruza-path-health.service`. Existing local target configuration is preserved
on updates. It does not restart flight, camera, VPN or observation services.
The logger account has CAP_NET_RAW and a write exception only for its output
directory; the unit has memory/task limits and low scheduling priority.

For QuadPi, copy the same staging folder, verify its source/peer addresses and
service names, inspect any existing `mesh-logger` service, then run the installer
with `quadpi`. The old mesh logger may provide radio RSSI/SNR/retry information
that this endpoint logger does not collect. Do not replace it without inspection.

```bash
systemctl is-enabled cruza-path-health.service
systemctl status cruza-path-health.service --no-pager
journalctl -u cruza-path-health.service -n 10 --no-pager
```

Verify growing samples under `/home/ebach/cruza-path-health/`, successful probes,
correct source/interface, `udp.error=null` and the intended service states.
Enabled boot startup still requires observation after a normal power cycle.

## Retrieve and report

Copy the exact relevant session segments over the existing private SSH path.
Keep original files from each Pi separate. On the Pi or a Python-equipped laptop:

```bash
python3 path-health.py --report SESSION-00001.jsonl SESSION-00002.jsonl
```

The JSON report groups by process/boot session and reports reachable/no-reply/
unavailable sample counts, mean successful RTT and latest observed state.
Pass each segment once. Counts describe the retained samples, not every packet
or total flight uptime. Correlate both Pi sessions with gateway application
evidence for a complete communications report.

## October 20 staging checks

Cruza was reachable by private SSH over LTE. Its existing communications service
was active with zero restarts. No direct mesh interface was present, consistent
with the architecture above. QuadPi was not reachable and the owner confirmed
it was not powered on. The existing observation publisher remained
disabled/inactive with `enabled=false`.

Twelve local/offline health tests passed on both the laptop and Cruza, including
wrong-route rejection, source binding, unavailable/error distinction, state
transitions, metadata minimization, malformed/truncated report handling and
existing rotation/heartbeat checks. Shell syntax and systemd unit validation
passed on Cruza. A bounded unprivileged live smoke run is used before installation;
passive capture requires the capability-bearing installed unit. The smoke run
produced three samples, all gateway-VPN probes reachable through `tailscale0`,
with mean RTT 125 ms. It ended normally after 25 seconds. Passive capture
reported `PermissionError`, as expected without CAP_NET_RAW. Existing router,
video and communications services remained active after the test; observation
sharing remained disabled. At that point the new boot service was staged.

Retained evidence:
`logs/2026-10-20/path-health-smoke/comms-330762bd-ccf3-48c3-9266-13e9603b6fb9-372371563346-2283-00001.jsonl`.

After the owner ran the installer, live verification on October 20 at
approximately 10:08 CDT confirmed the new service enabled and active/running,
exit status 0, zero restarts, CAP_NET_RAW present, and fresh samples with
`udp.error=null`. The latest gateway probe was reachable through `tailscale0`
at 125 ms. Existing router/video/original communications services remained
active and observation sharing remained disabled. The installed session is
`330762bd-ccf3-48c3-9266-13e9603b6fb9-4738628619788-17438`.
Cold-boot persistence still needs verification after a subsequent normal cycle.
The partner's QuadPi installation instructions are in
`HANDOVER-quadpi-path-health-2026-10-20.md`.
