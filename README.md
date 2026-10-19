# Hee Wing Fixed-Wing Build

Goal: fly a complete traffic pattern (takeoff, circuit, approach, landing) on a Hee Wing airframe, planned and monitored in QGroundControl.

## Hard requirement
- MAVLink telemetry over ELRS (single link for RC + telemetry to QGC).

## Components
| Part | Role | Notes to verify |
|---|---|---|
| Hee Wing airframe | Platform | Weight, motor/prop, CG |
| TBS Lucid Wing AIO 2-6S 50A | FC + ESC (all-in-one) | Firmware target (ArduPilot vs PX4), UART map, ESC protocol |
| BetaFPV ELRS 2.4G diversity RX | RC + MAVLink link | ELRS firmware version, UART/baud, MAVLink mode |
| Mateksys ASPD-4525 | Digital airspeed | Bus (I2C), pitot orientation/calibration |
| Mateksys M10Q-5883 | GPS replacement | Installed 2026-10-08, replacing NewBeeDrone BeeID Pro M10; post-swap wiring, configuration, and calibration pending verification |

The current GPS is the **Mateksys M10Q-5883**. See `docs/status.md` for the
replacement record. Historical BeeID snapshots predate the swap; fresh October 9
and October 13 exports and flight reviews are now available. GPS performance was
checked in those flights; consult the current status for remaining sensor checks.

## Airspeed integration — 2026-10-13

The Matek ASPD-4525 is detected on I2C bus 1 and verified in flight. Two full
five-minute calibration orbits produced a settled working ratio near 1.85.
Recommended next settings are **ARSPD_RATIO=1.85, ARSPD_AUTOCAL=0, ARSPD_USE=1**
for a controlled AUTO speed-control checkout; **these changes have not been
applied or flight-validated**. The latest actual snapshot still has ratio 1.8170,
AUTOCAL=1 and USE=0. See [main takeaways](docs/airspeed-integration-summary.md)
for evidence, the calibration mission, and remaining issues.

## Open decisions
1. Flight firmware: ArduPilot (Plane) is the usual choice for traffic patterns and landing sequences; confirm the AIO supports it.
2. UART budget: RX (ELRS/MAVLink), GPS, and airspeed (I2C) must all fit on the AIO's pads.
3. Ground station radio: ELRS TX module/radio that bridges MAVLink to the PC/phone (e.g. Wi-Fi backpack or USB).

The Pocket backpack is configured and verified. See `docs/elrs-backpack.md` for
the fixed SSID, firmware recovery images, QGroundControl ports, and status-field
behavior.

## Plan
1. Confirm the FC firmware and wiring map -> `docs/wiring.md`
2. Bench setup: flash FC, configure ELRS MAVLink, verify QGC connects -> `docs/elrs-mavlink.md`
3. Sensors: GPS, compass, airspeed calibration -> `docs/sensors.md`
4. Params baseline saved in `params/`
5. Traffic pattern mission in `missions/` (.plan files)
6. Ground tests: failsafes, control surface checks, motor direction
7. First flight, then log review in `logs/`

The 2026-10-09 AUTO flight, cruise-throttle change, and ESC calibration are recorded
in [the flight review](docs/flight-review-2026-10-09.md). Follow the
[flight-log workflow](docs/flight-log-workflow.md) to retrieve the next flight and
compare it against the retained baseline.

## Layout

The Pi/LTE/video companion implementation is in [companion/](companion/README.md).
See the [2026-10-14 live Pi audit](docs/pi-companion-audit-2026-10-14.md) for
verified hardware, software tests and deployment blockers. Android video, Pi LTE
and the new MAVLink connection still require bench validation.

- `docs/` build notes, wiring, config steps
- `params/` parameter files
- `missions/` QGC .plan files
- `logs/` flight logs

The local [fleet dashboard](dashboard/README.md) shows Cruza and quadpi live
video beside an interactive aircraft map and passive telemetry at
`http://127.0.0.1:8765`, preserving their direct QGroundControl connections.

[People and vehicle recognition](atr/README.md) runs on the same laptop and
marks people and vehicles in both aircraft video feeds.
