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
| NewBeeDrone BeeID Pro M10 | GPS (with ID module) | Protocol (UBX/NMEA), UART, compass included? |

## Open decisions
1. Flight firmware: ArduPilot (Plane) is the usual choice for traffic patterns and landing sequences; confirm the AIO supports it.
2. UART budget: RX (ELRS/MAVLink), GPS, and airspeed (I2C) must all fit on the AIO's pads.
3. Ground station radio: ELRS TX module/radio that bridges MAVLink to the PC/phone (e.g. Wi-Fi backpack or USB).

## Plan
1. Confirm the FC firmware and wiring map -> `docs/wiring.md`
2. Bench setup: flash FC, configure ELRS MAVLink, verify QGC connects -> `docs/elrs-mavlink.md`
3. Sensors: GPS, compass, airspeed calibration -> `docs/sensors.md`
4. Params baseline saved in `params/`
5. Traffic pattern mission in `missions/` (.plan files)
6. Ground tests: failsafes, control surface checks, motor direction
7. First flight, then log review in `logs/`

## Layout
- `docs/` build notes, wiring, config steps
- `params/` parameter files
- `missions/` QGC .plan files
- `logs/` flight logs
