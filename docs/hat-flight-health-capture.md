# Bounded HAT / Pi flight-health capture

`companion/flight-health.py` is deployed at
`/home/ebach/companion/flight-health.py` and smoke-tested on the Pi. It opens no
UART, sends no MAVLink or modem control commands, changes no network/service/FC
configuration and creates no boot service. An explicitly started capture persists
locally and can survive SSH loss when run under the transient systemd recipe below.
The smoke sessions have finished; **no flight capture is currently armed or running**.

## Before a separately authorized flight

Choose a session long enough for preflight, flight and landing: default30 minutes,
allowed10–7200 seconds. Create a fresh unique unit name. For a30-minute capture,
run in the Pi's owner terminal (sudo password only there):

```bash
session_unit="cruza-health-$(date -u +%Y%m%dT%H%M%SZ)"
sudo systemd-run --unit="$session_unit" --collect --uid=ebach \
  --property=AmbientCapabilities=CAP_NET_RAW \
  --property=CapabilityBoundingSet=CAP_NET_RAW \
  --property=NoNewPrivileges=yes \
  --property=RuntimeMaxSec=1860 --property=TimeoutStopSec=5 \
  /usr/bin/python3 /home/ebach/companion/flight-health.py \
  --seconds 1800 --interval 10 --output-root /home/ebach/cruza-health
systemctl status "$session_unit" --no-pager
journalctl -u "$session_unit" -n 10 --no-pager
```

The output supplies the **exact session directory**. Verify manifest and growing
`samples.jsonl`, `udp.error=null`, FC1/1 heartbeat freshness and resource/probe
results before relying on capture. Only fixed-wing FC1/1 heartbeat fields describe
aircraft armed state; QGC's own GCS heartbeat may set its armed bit. Inspect free
disk space. Capture ends after the bound; changing video state does not extend it.
Stop only the saved unit after landing with `sudo systemctl stop "$session_unit"`.
Starting this recorder never grants permission to upload, arm or start the aircraft.

## Recorded data and limits

Each sample carries UTC, monotonic time, session ID and collection duration;
manifest records boot ID and NTP synchronization. Samples are flushed/fsynced.
10 s sampling and60 s sparse probes bound overhead; storage stops at32 MiB/session.
Each subprocess has a3 s timeout. A slow sample can overrun the requested cadence
or duration; the transient unit provides a further independent lifetime bound.
There is no automatic reboot continuation. An absent `end.json` indicates an
interrupted/incomplete session. Scope old sessions deliberately before deletion.

- Modem presence, state, LTE technology, registration and signal-quality percentage.
  Extended read API queries are included, with missing metrics left unavailable.
  On this SIM7600, extended signal refresh is0 and RSRP/RSRQ/SINR/RSSI are absent.
  Serving cell band is not obtained; modem's allowed/current band set must not be
  reported as the serving band. No signal setup, AT command, reset or SIM query.
- Interface RX/TX/error/drop counters; route and NetworkManager device state.
  Internet ICMP probe is bound to wwan0 to1.1.1.1 once/minute; phone Tailscale path
  probe once/minute. VPN probe alone is not QGC delivery or proof of LTE selection.
  Interface byte deltas include all traffic/overhead, not carrier billing. Reset
  counters start a new epoch; reboot/renumbering requires explicit handling.
- Phone peer direct address/relay metadata and path-probe results. `Relay` may
  remain populated while a direct address is used; interpret with path probes.
- Passive tailscale UDP flow/message/sequence-step counts, no packet payload file.
  HEARTBEAT CRC is checked (signature not verified); other headers are candidates.
  FC heartbeat timestamps, age and maximum observed interarrival gap are kept.
  Outbound observations prove Pi transmission, not Android reception; confirm
  viewer/telemetry at the phone. Sequence discontinuities are not loss estimates.
- Sampled router endpoint counter lines; service state/restarts/activation times;
  NetworkManager/ModemManager and kernel event categories with journal timestamps.
  Full journal messages, SIM/equipment IDs and credentials are excluded. Bounded
  event queries flag possible truncation. Categories alone may not establish cause;
  retrieve a scoped/redacted journal later if detailed USB/recovery diagnosis needs it.
- Temperature, current/historical throttling mask, CPU cumulative ticks, load,
  memory/swap and uptime. Calculate CPU load from successive tick deltas. Software
  flags do not measure power supply current margin.
- Configured video profile/session bound, active-service windows, UDP5600 counts
  and correlated resources. Actual picture/latency and on/off actions need owner
  notes. No GPS/position payload is retained; consent remains pending.

Record owner UTC event notes for preflight, launch, turnaround, landing, mode/RC
observations, video picture/latency and interruptions. Note any clock disagreement.
FC time alignment will be checked against the specific flight DataFlash GPS/time
records afterward; current Pi NTP status alone does not prove FC alignment.

## Retrieval and post-flight report

After landing/disarming, copy the **recorded session ID**, never a wildcard/latest
assumption. From the laptop use existing private SSH/scp identity and host-key
alias, keeping access credentials outside project files. Example:

```powershell
scp -r -F NUL -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" `
  -o BatchMode=yes -o HostKeyAlias=10.229.125.15 `
  ebach@100.100.0.58:/home/ebach/cruza-health/EXACT_SESSION `
  logs/2026-10-14/
```

Check manifest/session/time boundaries, end reason, sample gaps, truncation and
boot/counter epochs; hash retained files. Confirm the actual flight date and save
under that date. Retrieve exact new FC BIN logs through the existing read-only
USB log tool after checking its interface and confirming disarmed state. Match
the airborne log to UTC events/mission, not newest filename. Preserve originals
and save a new parameter snapshot. Raw location-bearing logs stay local pending
deliberate sharing scope; no bulk Git push is part of this procedure.

The report will link session/BIN evidence and show modem registration/recovery,
signal availability, VPN path switches, telemetry gaps and phone observations,
thermal/throttle/USB/service behavior, resources, data consumed and completeness.
It will distinguish internet, VPN and QGC delivery. Aircraft findings include
actual route/max confirmed-home range, mission completion, voltage/reserve,
usable current only if sensing is verified, airspeed/groundspeed/wind, altitude,
GPS/EKF/vibration/control tracking and failsafe/events. No claimed clean flight
or HAT health beyond the evidence and capture coverage.
