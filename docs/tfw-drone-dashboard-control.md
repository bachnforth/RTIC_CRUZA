# TFW drone: dashboard command control

This is for the owner of **TFW drone** (`tfwdrone`, Tailscale `100.100.0.6`).
It lets the RTIC fleet dashboard send TFW drone the same commands it already
sends quadpi. Nothing changes on the aircraft until you install the filter
described below. Your RC transmitter stays the safety pilot's override.

## What the dashboard sends

The dashboard is the operator's laptop (Tailscale `100.100.0.23`). Every command
except the three immediate ones needs a review and a confirm click. Each is
answered by the FC's own `COMMAND_ACK`, and the dashboard never retries.

| Dashboard command | MAVLink sent to the FC (1/1) |
|---|---|
| Arm motors (current mode) | `COMPONENT_ARM_DISARM` param1 = 1, param2 = 0 (never forced) |
| Arm & fly mission | `DO_SET_MODE` GUIDED, arm, then `MISSION_START` with all params 0 |
| Arm & take off | `DO_SET_MODE` GUIDED, arm, `NAV_TAKEOFF` to 1–120 m |
| Fly to point & hold | `DO_REPOSITION` (`COMMAND_INT`, relative altitude, 1–120 m, within 1 km) |
| Loiter (circle) | `DO_SET_MODE` CIRCLE, using your FC's own `CIRCLE_*` radius and direction |
| Hold (immediate) | `DO_SET_MODE` BRAKE |
| RTL (immediate) | `DO_SET_MODE` RTL, using your `RTL_*` settings |
| Land (immediate) | `DO_SET_MODE` LAND |
| Disarm | `COMPONENT_ARM_DISARM` param1 = 0, param2 = 0 |

It also sends a 1 Hz GCS heartbeat, but only while a dashboard page is open. It
reads a few parameters (`PARAM_REQUEST_READ`: GCS id, `CIRCLE_*`, `RCMAP_THROTTLE`)
and reads the mission (`MISSION_REQUEST_LIST`/`_INT`). It requests telemetry
streams (`REQUEST_DATA_STREAM`, plus `SET_MESSAGE_INTERVAL` for
`EXTENDED_SYS_STATE` at 2 Hz), because without QGC there may be none.

The dashboard **never** writes parameters, uploads missions, sends RC
overrides, forces arming, or picks a mission start item.

Before *Arm & fly mission* the dashboard reads the mission back. It refuses to
send when:
- the first item isn't a takeoff;
- it climbs above 120 m or reaches more than 1.5 km from home;
- there is no home position yet;
- it changed after the operator reviewed it.

You keep uploading and checking missions with your own GCS, as now.

## Why a filter, and where it sits

The dashboard must not be able to send anything beyond that list, even by
mistake. The filter enforces this on your Pi, so the guarantee doesn't depend
on the laptop.

`partner/tfw-drone/safety_mavlink_filter.py` is the same filter quadpi runs
(RTIC-10-Quad commit `aad6ae2`, sha256 `78a88f08…14fc4c`). On quadpi it owns
the FC serial port. On TFW drone it doesn't need to: it connects to your
**mavlink-router TCP server** as one more client:

```
FC ─serial─ mavlink-router ─┬─ your existing endpoints (QGC, TCP 5760 …) unchanged
                            └─ TCP client: tfw-dashboard-filter ─ UDP 14551 ─ dashboard
```

The filter's rules:
- **Into the router (and so the FC):** only the exact command shapes above,
  addressed to system 1 / component 1. Everything else from the dashboard is
  dropped and counted.
- **Back to the dashboard:** whatever the router sends the filter, but only to
  addresses that sent it something in the last 5 seconds.

Its docstring lists all allowed shapes. It also passes one quadpi-specific
safety-device command (`MAV_CMD_USER_1`, 31010, keyed). The dashboard doesn't
send it, and ArduPilot ignores it.

## Install (on the TFW drone Pi)

1. **Check the FC.**
   - `SYSID_THISMAV` must be 1: the filter only passes commands addressed to 1/1.
     The dashboard currently sees TFW drone as 1/1.
   - Note your GCS id (`MAV_GCS_SYSID` on 4.7, `SYSID_MYGCS` before). The
     dashboard reads it and uses it, so nothing needs changing.
2. **Copy and test.**
   ```bash
   sudo mkdir -p /opt/tfw-dashboard-filter
   sudo cp safety_mavlink_filter.py test_flight_commands.py /opt/tfw-dashboard-filter/
   cd /opt/tfw-dashboard-filter && python3 -m unittest test_flight_commands
   ```
   Use the same Python that has pymavlink installed. All tests should pass.
3. **Install the service.**
   - Edit `tfw-dashboard-filter.service` if your Python path or mavlink-router's
     TCP port differs from `/usr/bin/python3` and `5760`.
   - `--udp-target 127.0.0.1:14599` is deliberate: nothing listens there. FC
     traffic only reaches the dashboard while the dashboard is talking to it.
   ```bash
   sudo cp tfw-dashboard-filter.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now tfw-dashboard-filter
   cat /run/tfw-dashboard-filter/status.json   # "to_qgc" should be counting up
   ```
4. **Allow UDP 14551 from the dashboard laptop only.** Use a Tailscale ACL, or
   on the Pi:
   ```bash
   sudo nft add table inet tfwdash
   sudo nft add chain inet tfwdash input '{ type filter hook input priority 0; }'
   sudo nft add rule inet tfwdash input udp dport 14551 ip saddr != 100.100.0.23 drop
   ```
   Make that rule persistent the way your Pi normally does.
5. **Tell us it's running.** We start the dashboard with
   `start-dashboard.ps1 -TfwControl 100.100.0.6:14551`, and TFW drone shows as
   **LIVE** in the command workflow.

**To undo:**
```bash
sudo systemctl disable --now tfw-dashboard-filter
sudo rm /etc/systemd/system/tfw-dashboard-filter.service
```
Nothing else on the aircraft is touched.

## Before flying with it

- **GCS failsafe.** The dashboard's heartbeat stops when the last dashboard page
  closes. If `FS_GCS_ENABLE` is set and the dashboard is your only GCS, closing
  the page triggers the failsafe.
- **Arming.** GUIDED arming needs throttle low on your transmitter. The
  dashboard's Loiter (circle) asks for throttle centred first: CIRCLE takes
  climb rate from the stick.
- **Taking over.** Move your mode switch to a different position, e.g. LOITER
  with throttle centred. ArduPilot only acts on the switch when it moves, so
  start with it in STABILIZE (or another manual mode), not AUTO.
- **Test order.**
  1. Props off: Arm, then Disarm.
  2. Props off: Arm & take off at 5 m, then Land. Motors spool up; it can't
     climb.
  3. Props on: a short mission close in.
  - The operator and the safety pilot confirm props on or off and a clear area
    before every arm, including retries.

## What has been tested

- **The filter allowlist:** 16 unit tests, including the `MISSION_START`
  variants that stay blocked (a chosen start or end item, another target,
  AUTO by mode change).
- **quadpi on 27 Oct 2026:** with the filter on its FC serial port, flew a
  mission launched by *Arm & fly mission*, RTL from the dashboard, landed and
  disarmed.
- **TFW drone arrangement, in SITL:** ArduCopter SITL's TCP port stood in for
  mavlink-router, the filter connected as a TCP client, and the dashboard was
  started with `-TfwControl`. The tested sequence:
  - *Arm & fly mission*: takeoff 10 m, two waypoints about 55 m out, LAND,
    disarm;
  - *Arm & take off* 8 m;
  - *Hold*;
  - *Land*.

  All were accepted, and the filter blocked nothing the dashboard sent.

**Not tested yet:** a real mavlink-router (expected to behave like any other
TCP client), and TFW drone itself.
