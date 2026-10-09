# Cruza launch investigation — 2026-10-08

Status updated 2026-10-09: attitude-axis mismatch and reversed elevator stabilization corrected on the bench. Flight validation and post-change calibration remain pending. No failed-flight log has been reviewed, so the exact crash sequence is unconfirmed.

## Confirmed settings

These values were set by the owner in QGroundControl during troubleshooting. They are not a fresh full parameter export; retain the historical snapshots unchanged.

| Parameter | Previous value | Confirmed final value |
|---|---|---|
| AHRS_ORIENTATION | 0 — None | 6 — Yaw270 |
| SERVO5_REVERSED | 1 — Reversed | 0 — Normal |
| RC2_REVERSED | 0 — Normal | 1 — Reversed |

S5 remains assigned to Elevator (`SERVO5_FUNCTION=19`). Aileron settings were not changed.

## Findings and bench verification

- Owner reports an immediate nose dive after launch in AUTO; motors continued running. Owner reports ample power and rules out propulsion as the issue.
- The conventional twin-motor T2 Cruza has separate elevator, ailerons and rudder. Its TBS Lucid Wing AIO is mounted upright with the long axis across the fuselage.
- With AHRS_ORIENTATION=None, holding the aircraft approximately 45 degrees nose down and wings level produced roll +0.7294 rad (~41.8 degrees) and pitch -0.01128 rad (~-0.65 degrees). The controller interpreted pitch motion as roll.
- After setting Yaw270 and rebooting, a nose-down test produced pitch -0.6544 rad (~37.5 degrees) and roll -0.0098 rad (~-0.6 degrees), confirming the pitch axis and sign for that pose.
- Elevator stabilization was then found to reinforce pitch disturbances. After setting S5 reversal to Normal, the owner confirmed nose up → elevator DOWN and nose down → elevator UP.
- RC2 reversal was set to Reversed; the owner confirmed pulling back on the right stick produces elevator UP. A final stick-direction check in both FBWA and MANUAL remains required.
- Owner confirmed right wing down → right aileron DOWN and left aileron UP. Final nose-up and both-direction roll attitude readings remain to be checked.

The attitude-axis mismatch and reversed elevator feedback are strong contributors to the failed launch. Their correction on the bench does not establish flight readiness or replace flight-log review.

## Evidence limits

- Latest workspace full parameter export is 2026-10-08 10:47 a.m., before the recorded GPS replacement and these corrections. It is not confirmed to match the failed flight.
- Saved QGC mission `Documents/QGroundControl/Missions/new111.plan` begins with NAV_TAKEOFF (22), minimum pitch 15 degrees, altitude 50 m relative to home. Upload and active mission item at launch were not confirmed.
- The historical snapshot has TKOFF_THR_MINACC=0, TKOFF_THR_MINSPD=0 and TKOFF_THR_DELAY=2. These launch settings need separate review before another automatic takeoff; they were not changed here.
- Preliminary framing/timestamp inspection of local `2026-10-08 10-28-18.tlog` gives 10:12:40–10:28:18 a.m. CDT with FBWA/RTL/Manual heartbeats and no AUTO heartbeat found. It was not identified as the reported flight and was not fully CRC-validated.
- Build notes list a 4S battery while Heewing's stock T2 PNP manual specifies 6S. The owner rules out inadequate propulsion; this remains a build-documentation discrepancy, not a diagnosed crash cause. Do not change battery voltage without verifying installed component compatibility.

## Required before the next flight

1. Inspect crash damage, wing/tail locks, elevator linkage and horn, servo travel, battery retention and CG at the manufacturer marks.
2. With both props removed, finish verifying measured pitch and roll against physical motion in both directions. Redo accelerometer and level calibration with the corrected orientation; use the appropriate aircraft cruise attitude for level calibration.
3. Repeat FBWA correction checks with centered sticks: nose down → elevator UP; nose up → elevator DOWN; right wing down → right aileron DOWN/left UP; left wing down → opposite correction.
4. Verify pull-back → elevator UP and correct roll commands in both FBWA and MANUAL. Confirm mechanically neutral surfaces and travel without binding.
5. Verify replacement GPS/compass configuration, sensor/pre-arm health and failsafes; resolve the temporary bench settings recorded in status.md.
6. Save a new full parameter export and retrieve the failed-flight .BIN log for desired/actual pitch, servo output, mode, mission state and estimator analysis.
7. Use an experienced fixed-wing pilot for a controlled FBWA checkout before retrying the full AUTO mission. Review and bench-test automatic launch separately.

## Sources

- [ArduPilot controller mounting/orientation](https://ardupilot.org/plane/docs/common-mounting-the-flight-controller.html)
- [ArduPilot four-channel setup and reversal checks](https://ardupilot.org/plane/docs/guide-four-channel-plane.html)
- [ArduPilot automatic takeoff](https://ardupilot.org/plane/docs/automatic-takeoff.html)
- [ArduPilot hand launch guidance](https://ardupilot.org/plane/docs/takeoff-landingpage.html)
- [Heewing T2 PNP manual](https://www.heewing.com/pages/t2-instruction-manual)
