# Cruza airspeed integration — main takeaways, 2026-10-13

The Matek ASPD-4525 is detected and working on the TBS Lucid Wing AIO running ArduPlane 4.7.1. Flight-log reviews support moving from calibration to a controlled AUTO speed-control test.

## What is verified

- Connect this sensor to **5V, GND, I2C SDA and SCL**. The CAN port supplies power but its CAN-H/CAN-L pins cannot communicate with the I2C sensor.
- Working configuration: **ARSPD_TYPE=1, ARSPD_BUS=1, ARSPD_PSI_RANGE=1, ARSPD_DEVID=141321**.
- Keep **ARSPD_SKIP_CAL=0**. Loosely shield the pitot's front and side openings from wind during zeroing, then remove the cover before testing or flight. ARSPD_OFFSET is measured automatically, not manually set to zero.
- Log 13 verified responsive measured airspeed. Log 14 ran automatic calibration but lasted only about two minutes.
- Log 15 completed the five-minute orbit and saved ratio **1.7256**, but still drifted during its final circles.
- Log 16 repeated the orbit starting from that baseline. Its final-minute ratio ranged **1.852–1.880**, with **0.1% net change**; the final working estimate was about **1.853**. The controller saved an intermediate value of **1.8170**.
- The sensor remained healthy through these reviewed flights. Log 16 had no recorded EKF faults or in-flight clipping before flare; six clips per IMU occurred at the landing stop.

## Recommended next settings — not yet applied or flight-validated

| Parameter | Current verified snapshot | Recommendation |
|---|---:|---:|
| ARSPD_RATIO | 1.81702554 | **1.85**, explicitly save |
| ARSPD_AUTOCAL | 1 | **0**, freeze the calibration |
| ARSPD_USE | 0 | **1**, for a controlled AUTO speed-control test |
| AIRSPEED_CRUISE | 15 m/s | Retain for the initial checkout |
| AIRSPEED_MIN / MAX | 10 / 22 m/s | Retain provisionally; limits still need validation |
| SCALING_SPEED | 15 m/s | Leave unchanged |

Save and read back the ratio and AUTOCAL before enabling USE. With USE=0 the pitot is logged but does not control automatic throttle; it can still affect stabilization speed scaling. The calibration flights therefore do not validate airspeed-controlled AUTO performance.

## Remaining issues

- **Stall margin remains unverified.** A 10 m/s minimum meets a 25% margin only if actual stall speed is no more than 8 m/s.
- **Propulsion-current measurement is invalid:** approximately 0.19–0.20 A even with both motors running. Do not rely on its consumed-capacity/remaining-percentage estimates. Check whether the external ESC power path bypasses the AIO current sensor.
- Historical relaxed arming settings persist: **ARMING_MAGTHRESH=300**, **ARMING_SKIPCHK=4096**, and **BATT_ARM_VOLT≈13.2 V**. These are separate review items, not resolved by sensor calibration.
- Inspect the aircraft after a hard landing. Brief landing-stop clipping does not indicate sustained cruise vibration.

## Calibration route and evidence

The prepared [QGC mission](../missions/Cruza_Airspeed_Calibration_5min_60m_2026-10-13.plan) adds a **300-second timed loiter at 60 m relative altitude**, using **WP_LOITER_RAD=60**, before the existing approach. Expected total flight time is 7–8 minutes. The subsequently flown loiter center was moved approximately 73 m west of the generated preview; the generated file is not an exact record of the flown mission.

See the [confirmation-flight review](flight-review-2026-10-13-calibration-confirmation.md), [plot](../logs/2026-10-13/download-112145_796901/log_00016.airspeed-review.png), and [actual postflight parameter snapshot](../params/cruza_params_2026-10-13_112145_796901_postflight.params). Reports, plots, metrics, parameter snapshots and analysis tools accompany this summary; large original BINs remain retained locally and are identified by size and SHA-256 in each report.
