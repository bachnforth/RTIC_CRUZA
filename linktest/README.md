# Cruza → quad data-link test

**Question this answers:** while the Cruza is flying, and as it gets farther away,
can its companion Pi pass data to each quad's Pi, reliably and fast enough?

The test sends numbered test packets from the Cruza to every quad for the whole
flight, logs what each quad actually receives, and afterwards builds a report
that lines those logs up with the Cruza's flight log (GPS position, height,
armed time). The report gives each quad a **PASS / FAIL / INCONCLUSIVE** verdict
and shows where and when data stopped getting through.

Nothing in this folder talks to a flight controller. The tool uses its own UDP
port (15700), opens no serial port, sends no MAVLink, and changes no route,
firewall, service or parameter.

## How the data travels

The Cruza has no mesh radio. Its only path to the quads today is LTE:

```text
Cruza Pi --LTE--> internet / Headscale VPN --> quad Pi (VPN address 100.100.0.x)     <- "vpn" path (default)
Cruza Pi --LTE--> VPN --> ground gateway (alien03) --915 MHz mesh--> quad Pi (10.223.x)  <- "mesh" path (optional, see below)
```

So "distance" here mostly tests LTE coverage at range and height, the VPN
(direct vs relayed), and each quad's own network link, rather than a radio link
between the aircraft. The report records which interface and VPN path were in use
for every packet so you can tell them apart.

Terms used below:

- **Probe**: a small numbered test packet (300 bytes, 5 per second per quad by default).
- **Echo**: the small program on each quad that logs probes and answers each one.
- **Burst**: every 30 s, 50 kB of data sent quickly, to check bulk transfer.
- **RTT** (round-trip time): time from the Cruza sending a probe to getting the answer.
- **DERP**: a Tailscale relay server used when two VPN devices cannot reach each other directly; slower.
- **SSH**: the secure remote login the laptop already uses to run commands on the Pis.

## Files

| File | Runs on | Purpose |
|---|---|---|
| `plan.json` | everywhere | Addresses, SSH logins, rates and pass/fail criteria. The one file to edit. |
| `linktest.py` | Cruza Pi and quad Pis | Sender, echo, ground check, live view. Python 3 standard library only. |
| `run-linktest.ps1` | Windows laptop | Deploys, starts, watches, stops and collects over SSH; builds the report. |
| `report.py` | laptop | Post-flight report (HTML + CSV). |
| `test_linktest.py` | anywhere | Automated tests: `python linktest/test_linktest.py` |

## One-time setup

1. **TFW drone login.** Its Pi belongs to the partner team. Put the SSH login in
   `plan.json` (`"ssh": "user@100.100.0.6"`), or ask them to copy `linktest.py` and
   `plan.json` into `~/linktest/` on that Pi and run, before each test:
   `cd ~/linktest && nohup python3 linktest.py echo --name tfwdrone > ~/linktest-logs/echo-console.log 2>&1 &`
   and afterwards send you the `~/linktest-logs/*_echo_*` folder.
2. **VPN access rule.** The Headscale policy must let `tfwcruza` (100.100.0.58) send
   UDP 15700 to each quad. The ground check below reports "no answer from echo" if not.
3. **Quad positions (optional but better).** If the quads stay in one place,
   enter each one's `"position": {"lat": .., "lon": .., "alt_m": ..}` in `plan.json`
   (alt_m is above sea level). The report then measures range from the Cruza to each
   quad; otherwise it uses distance from the Cruza's launch point. If a quad flies,
   pass its flight log instead (see "Report").
4. `.\linktest\run-linktest.ps1 deploy` copies the tool to the Cruza and quads.
   Repeat after editing `plan.json`.

## Test day

### On the ground (props off)

1. Power the Cruza (Pi, LTE) and the quads; wait for the VPN to come up.
2. `.\linktest\run-linktest.ps1 start` — starts the echoes, runs the ground check,
   then starts the sender. If any check fails the sender is not started; fix it, or
   use `-Force` if a quad is intentionally absent.
3. `.\linktest\run-linktest.ps1 watch` — confirm every row is green.

The sender stops on its own after `duration_s` (1 hour); the echoes 15 minutes later.

### Flight profile

Reuse the proven 20 Oct corridor so results are comparable. Suggested: climb to
the normal 100 m, then fly outbound in steps (0.5, 1, 1.5, 2, 2.5 km...) with a
60 s orbit at each step, then return. The orbits give each distance enough
packets to judge. The 20 Oct flight lost RC at 3.6 km, so keep the planned
maximum inside the RC range you are prepared to rely on. Optionally repeat at a
second height to see whether height changes LTE behaviour.

Write down the take-off and landing times.

### Monitoring during the flight

- `.\linktest\run-linktest.ps1 watch` shows, per quad, every second:
  **UP 10s** (share of probes the quad confirmed in the last 10 s), **DOWN**
  (answers that made it back), RTT, **SILENT** (seconds since the last answer),
  bursts, the outgoing interface and VPN path, plus LTE signal and Wi-Fi state.
  Green = at or above the 90% target; yellow = degraded; red = failing or silent.
- This view itself travels over the Cruza's LTE link, so it can freeze when the link
  does. Open a second window with `watch -Quad quadpi` — that view comes from the
  quad (over the mesh/local network), so it keeps updating and shows whether data
  is still arriving even if the Cruza view stalls.
- Logging continues on the Pis regardless of whether anyone is watching.

### After landing

1. `.\linktest\run-linktest.ps1 stop`
2. `.\linktest\run-linktest.ps1 collect` — copies all sessions from the last 12 hours
   into `linktest-results\<date_time>\`.
3. Pull the Cruza's flight log over USB as usual (`tools\pull-flight-logs.py`).
4. `.\linktest\run-linktest.ps1 report -CruzaLog <path\to\log_000NN.BIN>` — builds and
   opens `report\report.html`. To add a flying quad's track, run `report.py` directly
   with `--quad-log quadpi=<its .BIN or .tlog>`.

## What the report contains

- Verdict per quad, and each check with the measured value and requirement.
- Timeline: Cruza distance and height, delivery %, RTT, LTE signal and Wi-Fi state.
- Delivery and RTT by distance (250 m bins), and the furthest distance at which
  every bin still met the 90% target.
- Map of the flight with each packet coloured delivered / lost.
- Bulk-data bursts: completeness and throughput.
- Every loss longer than 1 s with time, distance, height, route and LTE signal.
- CSV files (every probe, every window, outages, bursts) and `summary.json`.

Only the airborne (armed) part of the session counts toward the verdict.
**Inconclusive** means nothing failed but the evidence is thin: too few probes,
no flight log, or the Cruza did not fly at least `min_distance_m`.

### Default pass criteria (edit under `criteria` in `plan.json`)

| Check | Default | Why |
|---|---|---|
| Overall delivery | ≥ 98% | Data must actually arrive |
| 10 s windows at ≥ 90% delivery | ≥ 95% of windows | No long degraded stretches |
| RTT, 95th percentile | ≤ 1000 ms | Answers usable for coordination |
| Longest continuous loss | ≤ 5 s | Matches a short RC-style failsafe gap |
| Bursts fully delivered | ≥ 90% | Bulk data gets through |
| Median burst throughput | ≥ 64 kbit/s | About twice the Cruza's measured telemetry rate (≈27 kbit/s) |

These are starting points, not requirements anyone has signed off. Set them to
whatever the quads actually need to receive.

## Data use and load

Per quad, about 3 kB/s outbound (probes plus bursts) and 1.3 kB/s of answers.
For two quads that is roughly 35–45 MB per hour of testing on the LTE SIM,
about three times the Cruza's normal telemetry (12 MB/h on 20 Oct). Lower
`rate_hz` or the burst size in `plan.json` to use less. The sender runs at lowered priority; CPU use on the Zero 2 W is
small. Logs rotate and are capped at 256 MB per session; if the SD card gets low,
per-packet records are dropped first and the report says so.

## Optional: testing the mesh path

Only after the steps in `docs/handover-2026-10-20-cruza-lte-flight.md` §5 (on the
`lte-bvlos-flight-review` branch): the
Cruza accepts the gateway's route (`tailscale set --accept-routes`), the gateway
and quad radios are up, and each quad has a route back to `100.64.0.0/10` via the
gateway. Then set `"enabled": true` on the quad's `mesh` path in `plan.json`, and
add `"bind": ["<quad mesh IP>", "<quad VPN IP>"]` to that quad so answers leave from
the address they were sent to. Both paths are then tested side by side and appear
as separate rows (`quadpi/vpn`, `quadpi/mesh`).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Ground check: "no answer from echo" | Echo not running on that quad, VPN rule blocks UDP 15700, or (mesh) no route back |
| "This Pi's VPN address" fails | Tailscale down on the Cruza, or the plan has the wrong address |
| Wi-Fi up on the Cruza | Fine on the ground; it should drop out after take-off. The report flags packets sent while it was up |
| Clock not synchronized | Report time-matching with the flight log may be off; check `timedatectl` on the Cruza |
| Watch says "status is old" | The sender or echo stopped; check `~/linktest-logs/*-console.log` on that Pi |
