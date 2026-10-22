# Cruza calibration confirmation — 2026-10-13, log 16

The confirmation flight demonstrates a substantially more settled airspeed ratio during the final circles. The working ratio ends near **1.853**, with only **0.10% first-to-last change during the last loiter minute**, although it fluctuates across 1.8525–1.8796 in that minute. Recommend freezing **ARSPD_RATIO=1.85** and disabling **ARSPD_AUTOCAL=0**, then testing **ARSPD_USE=1** in a controlled automatic-speed checkout. This is a sensor setup recommendation, not a finding that all aircraft limits and preflight issues have been validated. No aircraft settings were changed in this review.

## Evidence and integrity

- Log 16, onboard index timestamp October 13, 2026, 11:18:40 a.m. CDT.
- Original BIN: `logs/2026-10-13/download-112145_796901/log_00016.BIN`, 21,594,112 bytes, matching onboard index.
- SHA-256: `b9b1f01b27420f35be5b192002975fbeb216f8ebf8ff4b2b66a18cfc3fbbf53b`.
- Complete read-only USB snapshot, 1245/1245 indexes: `params/cruza_params_2026-10-13_112145_796901_postflight.params`.
- No parsed BAD_DATA records or logger drops. Downloaded while disarmed over COM17, QGC closed. Firmware ArduPlane 4.7.1, dbe79216.
- AUTO is the only logged mode. Arm-to-disarm duration **461.10 s**, approximately 7 minutes 41 seconds.

## Calibration

The flight starts with ARSPD_RATIO=1.72559154, AUTOCAL=1, USE=0. The timed loiter command begins at controller time 194.095091 s and completes at 511.394921 s, an interval of 317.30 s including entry and heading exit. The commanded orbit time is 300 seconds.

| Evidence | Ratio |
|---|---:|
| Initial saved baseline | 1.725592 |
| Saved update at controller time 304.896 s | 1.817026 |
| Current controller value after reconnect | 1.81702554 |
| Last loiter minute, minimum–maximum | 1.852484–1.879632 |
| Last loiter minute, median | 1.866614 |
| Last loiter minute, first → last sample | 1.857161 → 1.859002 |
| Last loiter minute, net change | +0.099% |
| Final 30 s of usable-pressure samples | 1.848592–1.856372 |
| Final usable-pressure sample | 1.853104 |

The working ratio is reconstructed from logged `ARSP.Airspeed² / ARSP.DiffPress`, retaining differential pressure >20 Pa. The exact MS4525 raw-speed/pressure logging implementation supports this reconstruction. The controller only persists larger changes, so the saved 1.8170 is an intermediate value, not the final in-memory estimate. [4.7.1 logging implementation](https://raw.githubusercontent.com/ArduPilot/ardupilot/Plane-4.7.1/libraries/AP_Airspeed/AP_Airspeed.cpp), [calibration persistence implementation](https://raw.githubusercontent.com/ArduPilot/ardupilot/Plane-4.7.1/libraries/AP_Airspeed/Airspeed_Calibration.cpp).

This differs from log 15, where the ratio decreased approximately 2.6% over the last loiter minute. Log 16 still has bounded variations, but its final circling window has little net drift, and the subsequent approach settles near 1.853. A rounded **1.85** captures that settled tail and is within 1% in speed scale of the last loiter minute's median. It is not an independently measured wind-tunnel calibration or proof of absolute speed accuracy. There is no basis for restoring 2.00 or the previous 1.7256 baseline.

## Flight and sensor review

- All recorded airspeed health values H=1; U=0 throughout. Maximum sample gap 0.100898 s. No sensor dropouts or ERR records.
- EKF fault flags FS=0 and GPS-check flags GPS=0 for both cores. GPS has 26–32 satellites and HDOP 0.46–0.57.
- Settled-loiter window (controller time 214.095–511.395 s, first 20 s after item activation omitted): altitude **57.50–62.48 m** around a 60 m target; median 59.93 m. Pitch/roll tracking RMS **1.56/2.27 degrees**. Commanded roll varies around the orbit and actual roll generally follows it; this is not evidence of a sustained uncontrolled oscillation.
- Last loiter minute: median airspeed **15.81 m/s**, groundspeed **15.53 m/s**, altitude **60.02 m**. The ratio varies during this interval, and wind prevents simple equality of airspeed and groundspeed from being a calibration test.
- Median settled-loiter throttle is 64.02%, versus 62.10% in log 15; wind/conditions and speed scaling differ, so this does not establish a propulsion problem or justify a trim change.
- No accelerometer clipping before flare. At controller time **545.776 s**, near the landing stop, each IMU records **6 clipping events**. These are brief landing-associated shocks; inspect the aircraft if touchdown was hard. No sustained in-flight clipping is apparent.
- Mission completes timed loiter, approach, NAV_LAND, flare, and disarm. Flare message: 2.9 m, sink 1.45 m/s, speed 17.5 m/s, target distance 62.7 m. Final reported LAND distance **11.37 m**. No automatic-disarm message; touchdown quality is not established.
- Battery voltage **15.77–16.59 V**. Logged current remains implausible at **0.180–0.198 A**. Current-based remaining capacity is unreliable.
- Sensor temperature **27.80–29.17 C**. Flight offset is about 59.9771 Pa; live offset after reconnect is 59.2196 Pa, from a subsequent startup calibration. These are different boots, not in-flight offset changes.

## Next configuration and validation

Recommended QGC changes, **not applied**:

| Parameter | Current post-reconnect | Recommended |
|---|---:|---:|
| ARSPD_RATIO | 1.81702554 | **1.85**, explicitly save |
| ARSPD_AUTOCAL | 1 | **0**, stop adaptation |
| ARSPD_USE | 0 | **1**, for a controlled automatic-speed checkout after saving the above |

Retain CRUISE=15 m/s, MIN=10, MAX=22, SCALING_SPEED=15, SKIP_CAL=0, TYPE=1, BUS=1, PSI_RANGE=1. The minimum remains unvalidated against stall speed; a 10 m/s minimum provides the documented 25% margin only if actual stall speed is no higher than 8 m/s. Retaining these values is not a validation of stall or structural limits. Do not alter TECS/stabilization gains merely because the sensor is being enabled.

Save/read back ratio and AUTOCAL before enabling USE. Confirm startup zeroing and blow response; use an attended test at safe altitude with an available MANUAL/FBWA recovery, and review demanded/actual speed, height, and throttle after enabling. Previously documented current-monitor and relaxed pre-arm-check issues remain separate unresolved items. [Airspeed calibration procedure](https://ardupilot.org/plane/docs/calibrating-an-airspeed-sensor.html), [airspeed targets and speed scaling](https://ardupilot.org/plane/docs/airspeed-parameters-setup.html).

## Artifacts

- [Measured airspeed, flight response, and ratio plot](../logs/2026-10-13/download-112145_796901/log_00016.airspeed-review.png).
- `log_00016.airspeed-review.json`, `log_00016.summary.json`, and original BIN in the same directory.
- Analysis is reproducible with `tools/analyze-flight-log.py` and `tools/review-airspeed-log.py`. Large parsed records are excluded from Git.
