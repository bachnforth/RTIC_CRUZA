# Cruza: 5 km outbound/return mission and HAT flight-health handover

Date: 2026-10-14. Repository: https://github.com/bachnforth/RTIC_CRUZA,
branch `main`. Local checkout:
`C:\Users\ebach\Documents\ChatGPT\Fixed wing Cruza`.

## User's next objective

Create a reviewed fixed-wing route that goes **5 km from home and returns**,
then prepare a post-flight report focused on **SIM7600 LTE HAT health**, with
other useful aircraft findings included. Treat 5 km as maximum outbound
distance from home, not total route length: the direct out-and-back is about
10 km before takeoff, turns, loiter and landing. Confirm this interpretation
with the owner while gathering route constraints.

This handover authorizes route preparation and log-analysis planning. It does
not authorize mission upload, arming, mode changes, motor operation, flight,
or changes to failsafes/arming checks. Create reviewable artifacts first; obtain
the owner's separately required authorization before such operations.

## Latest verified integration state

- Pi `TFWCRUZA`, Zero 2 W, user `ebach`, Raspbian 13 Trixie 32-bit.
- SIM7600G-H HAT(B), SKU 19485: modem USB detected, QMI data on `wwan0`,
  NetworkManager profile `cruza-lte`, APN `america.bics`.
- Headscale server `https://headscale.rotopter.com`; preserve enrollment/policy.
- Pi 100.100.0.58, owner phone 100.100.0.57, laptop 100.100.0.23.
- TBS Lucid Wing AIO ArduPlane 4.7.1, source1/1; UART2 MAVLink2/115200/options0.
  Prior FC heartbeat was disarmed/AUTO; **recheck live state**, do not assume it.
- Router/firewall enabled and active; listener Pi 100.100.0.58:14560,
  TCP disabled. Firewall allows only owner phone through tailscale0 to UDP14560.
- Android QGC 5.0.8 64-bit: owner confirmed phone connection and completed
  parameter download after reconnect. Parameter export/count comparison not saved.
- Phone link: UDP local port14550, add/save server100.100.0.58:14560,
  Emit heartbeat enabled, GCS source255/190, forwarding disabled. UDP auto-connect
  is under **Comm Links**, despite link dialog's outdated General reference.
- Corrected packet observer saw phone traffic and FC1/1 telemetry returning;
  a PARAM_VALUE header was observed. Router UART TX became nonzero after restart.
- Final 20:38:48 UTC check: router/firewall, usage and LTE-health timers active;
  video inactive; RN08 Wi-Fi connected/preferred metric 600, LTE metric 700.
  Pi 48.9 C, 277 MiB available RAM, swap 0, throttled 0x0. UART since restart:
  26,825 handled, CRC/sequence errors 0, UART transmitted1,200.

Evidence: [QGC continuation](qgc-lte-testing-2026-10-14.md),
[original wiring/access handover](qgc-lte-handover-2026-10-14.md),
[deployment guide](../companion/README.md), [initial audit](pi-companion-audit-2026-10-14.md).

## Outstanding integration checks before flight acceptance

1. Verify fresh FC disarmed state and all visible QGC telemetry fields; save a
   full parameter export and compare UART2, ELRS/GPS and safety settings.
2. Download/compare the existing mission. Do not upload a new mission as a
   connectivity test.
3. Confirm Android video: UDP h.264, port5600. Start only with a ready viewer:
   `sudo systemctl start cruza-video`. Economy 640x480/15 fps/300 kbps, 120 s limit,
   no boot autostart. Record actual picture, latency and combined telemetry load.
4. Prove QGC and a fresh parameter reply with Pi Wi-Fi disconnected. Earlier
   LTE-only SSH/phone reachability passed, but **LTE-only QGC/video did not yet
   run**. First verify an independent 90 s RN08 restoration timer, then disconnect
   wlan0 through private-IP SSH; confirm wwan0 sole internet default and restore
   RN08. Full procedure is in the original handover; inspect live profile/unit
   names, never reuse an existing timer blindly.
5. Investigate startup/reconnect behavior on the bench. Initial connected QGC
   stalled downloading with UART TX 0; a bounded router restart restored forwarding
   and owner confirmed download after reconnect. Root cause remains unknown.
   Android router sequence-loss counters reported 97–98%; these counters alone
   are not measured VPN loss. Distinguish sequence behavior, duplication,
   app retries and actual dropped packets using timestamped observations.

Current known safety settings from earlier export include GCS failsafe disabled
(`FS_GCS_ENABL=0`), fence disabled, `ARMING_SKIPCHK=4096`,
`ARMING_MAGTHRESH=300`, low/critical battery actions1. Do not promise LTE loss
causes RTL. Preserve ELRS SERIAL4 MAVLink2/460800 and GPS SERIAL6 protocol5/115200.
Do not change these settings without owner approval.

## Route preparation

Ask for confirmed home/takeoff/landing coordinates, desired outbound bearing
or turnaround location, operating area and jurisdiction, altitude convention
and limits, terrain/obstacles/airspace constraints, takeoff/landing method,
cruise speed, battery capacity/condition and reserve, forecast wind, and independent
RC/return arrangements. Do not infer today's home from historical logged GPS.
Use current authoritative terrain/airspace/rules/weather sources where needed.

Prepare an editable QGC `.plan` plus a waypoint/distance/altitude summary and
map for owner review. Plan fixed-wing turns and return/landing explicitly.
Estimate total route length, travel time and energy/reserve from measured aircraft
performance; account for return headwind and maneuvering. Record assumptions
and unresolved feasibility constraints. A 5 km outbound waypoint is a requested
geometry, not evidence of sufficient endurance, coverage or flight readiness.
Review any change against the existing mission and aircraft configuration before
separately authorized upload. Do not arm/start flight from this planning request.

## Capture HAT/Pi evidence before the flight

FC `.BIN` logs alone generally do not capture modem health, Pi thermal/power
state or VPN path. Arrange companion measurements **before** any owner-authorized
flight, then retrieve them afterward. Existing usage counters are byte estimates,
not carrier billing; LTE-health timer is not a complete flight recorder.

Prepare a bounded, read-only companion logger with UTC timestamps, session ID,
and local persistence, including:

- Modem registration, bearer/interface state, technology/band, available
  signal-quality metrics (RSRP/RSRQ/SINR/RSSI when the actual modem/API exposes
  them), and NetworkManager/ModemManager disconnect/reconnect events.
- LTE route/interface selection, RX/TX and error/drop counters, data consumed;
  sparse reachability/latency samples with a documented probe interval/target.
  Distinguish internet reachability, VPN reachability and QGC data delivery.
- Tailscale direct/relay path and changes, plus router per-endpoint message
  counters, CRC/sequence anomalies and heartbeat gaps. Interpret counter
  semantics; avoid using raw sequence-loss percentages as network loss.
- Pi temperature, `vcgencmd get_throttled` (current and historical flags), CPU,
  RAM/swap, uptime/reboots, service restarts, kernel USB/modem errors. Software
  observations cannot establish supply-current margin; measure power separately
  if necessary. GPS/flight position for correlation only with owner's consent.
- Video profile and on/off windows, observed phone latency/interruption notes,
  and CPU/network impact if video is used.

Use available tools first, inspect supported modem queries rather than assuming
every signal metric exists, and bound sampling overhead/storage/data costs.
Do not introduce modem resets, control commands, automatic aircraft actions or
replay queues. Record UTC time alignment and any offset between companion, FC
GPS time and owner flight events. Exclude credentials and full SIM identifiers.
Aircraft logs contain location data: do not bulk-push unrelated/raw logs without
deliberate scope review.

## Post-flight report

Retrieve the new FC DataFlash logs and companion session files; identify the
exact flight by timestamps and mission, not just newest filename. Existing
`tools/pull-flight-logs.py`, `tools/analyze-flight-log.py`,
`tools/review-airspeed-log.py` and `tools/compare-flight-logs.py` may be reused
after reading their interfaces. Dependencies are under `.flightlog-deps`.

Deliver a report with evidence-linked plots/tables and a clear HAT-health finding:
coverage/registration changes, disconnect duration and recovery, VPN relay/direct
switches, telemetry gaps/latency, thermal/throttling/USB stability, resource use,
data budget and correlation with range/location/flight phase where available.
Separate observed facts, likely causes and unsupported conclusions. If companion
data is absent, explicitly state HAT health cannot be established from FC logs.

Include useful aircraft findings: actual route and maximum home distance, mission
completion, battery voltage/current/consumption and reserve, airspeed versus
groundspeed/wind, altitude/terrain clearance where supported, GPS/EKF health,
vibration, attitude/control tracking, failsafe/events, and log completeness.
Prioritize anomalies with timestamps, severity, evidence and actionable next
checks; do not claim a clean log proves overall flight readiness.

## Access and diagnostics

```powershell
ssh -F NUL -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" -o BatchMode=yes -o ConnectTimeout=8 -o HostKeyAlias=10.229.125.15 ebach@100.100.0.58
```

Source `/home/ebach/companion`, runtime `/opt/cruza/cruza.py`, config
`/etc/cruza/config.json`. Passwords must be entered only in the owner's interactive
Pi terminal; sudo credentials may expire. No credentials belong in chat or Git.
Do not reinstall working components or re-enroll VPN nodes. Only guarded shutdown
is permanently password-free; do not execute it during testing.

New tools copied to Pi:

- `sudo python3 /home/ebach/companion/observe-qgc-udp.py --seconds 15`:
  passive metadata observation, ETH_P_ALL includes both directions, candidate
  MAVLink headers only, no payload persistence or CRC validation.
- `sudo bash /home/ebach/companion/debug-router.sh`: **bench-only**, interrupts
  normal routing for eight seconds with independent 25 s restoration and EXIT
  restart. Config copied outside the normal runtime directory, TCP forced off.
  Do not run during flight. Corrected version was exercised successfully.

Second phone requested but **not configured**. Need its Tailscale IP and intended
authority. Proposed separate Pi UDP14561, phone local14550, QGC system254;
current phone keeps Pi14560/system255. Current server sends to last sender, so
do not simply admit both phones to one server endpoint. Forwarding stays disabled
on both QGC apps. Preserve phone-only policy when adding an explicit second peer.

## Paste into the next chat

> Read `docs/mission-hat-handover-2026-10-14.md` in RTIC_CRUZA and continue from
> the verified Android QGC connection and completed parameter download. I want
> a reviewed fixed-wing route that reaches 5 km from confirmed home and returns,
> followed after flight by a report focused on LTE HAT health and useful aircraft
> log findings. Gather the home/route/altitude/endurance constraints, prepare the
> QGC plan for review, finish the remaining LTE-only/video bench checks, and set
> up companion health logging before flight so modem/Pi health can be assessed.
> Preserve ELRS/GPS and flight settings. Do not upload, arm, change flight modes,
> run motors or start a flight without my separate instruction.
