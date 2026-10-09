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
replacement record. Existing parameter snapshots and BeeID test results predate
the swap; a post-swap parameter export has not yet been recorded.

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
- `docs/` build notes, wiring, config steps
- `params/` parameter files
- `missions/` QGC .plan files
- `logs/` flight logs
