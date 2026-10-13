# Cruza airspeed integration flight review — 2026-10-13

The MS4525 airspeed sensor is now detected and produces responsive, continuous flight measurements. Log 13 completed AUTO takeoff, the circuit, NAV_LAND, flare, and disarm with no recorded ERR messages, EKF fault flags, GPS-check flags, accelerometer clipping, or logger-dropped records. This flight verifies measurement operation, but does not verify the sensor's scale calibration or automatic airspeed/throttle control: ARSPD_USE=0, ARSPD_AUTOCAL=0, and ARSPD_RATIO=2 throughout.

## Evidence and retrieval

- Downloaded onboard log 13 over USB COM17 while the controller was disarmed. Index timestamp: October 13, 2026, 9:46:20 a.m. CDT. Flight records span controller time about 350.15–496.65 s, including approximately 132 s from arming to disarm.
- Original file: `logs/2026-10-13/download-095339_683885/log_00013.BIN`, 6,684,672 bytes, matching the onboard index.
- SHA-256: `feec00ef50a5f6fad811daee18abfaf232b56229169c47d4c9eb800d529adde2`.
- No parsed BAD_DATA records. DSF.Dp remained zero. Startup zeroing occurred before logging began, so the sheltered conditions during calibration cannot be established from this log.
- Firmware: ArduPlane 4.7.1, dbe79216, TBS_LUCID_H7_WING_AIO.
- Retrieved a complete live parameter snapshot, 1245/1245 indexes, to `params/cruza_params_2026-10-13_095339_683885_postflight.params`. No aircraft settings were changed.
- Logs 12 and 11 were also retrieved; hashes exactly match their previously retained October 9 copies. They are historical records, not additional October 13 flights.

## Airspeed sensor

| Item | Flight evidence |
|---|---|
| Sensor configuration | ARSPD_TYPE=1, BUS=1, DEVID=141321, PSI_RANGE=1 |
| Sensor health | All 1464 ARSP samples have H=1 and Hp=1 |
| Measurement continuity | Maximum sample interval 0.10086 s; no cruise samples below 3 m/s |
| Throttle/speed control use | ARSPD_USE=0; every ARSP.U sample is 0 |
| Calibration configuration | AUTOCAL=0, RATIO=2, SKIP_CAL=0 |
| Flight zero offset | 65.2273 Pa, unchanged in recorded ARSP samples |
| Live offset after reconnect | 64.1436 Pa; a different boot/calibration, not an in-flight change |
| Cruise reading | Median 17.16 m/s; range 15.69–19.27 m/s |
| Same waypoint-5 straight leg | Median pitot airspeed 16.85 m/s; median GPS groundspeed 15.89 m/s |
| Maximum recorded airspeed | 26.56 m/s, near takeoff/level-off |
| Landing approach, before flare | Median 16.89 m/s; range 15.87–18.12 m/s |
| After disarm, nearly stationary | Median 2.18 m/s; range 0.32–3.16 m/s |

Measurements rise with launch acceleration, remain stable through cruise, and fall with landing deceleration. This is evidence against a blocked or disconnected pressure path. Small ground readings can reflect wind and low-pressure sensor noise; the post-disarm values alone do not establish a bad zero. Temperature ranged 23.31–24.77 C.

The difference between airspeed and GPS groundspeed does not prove calibration accuracy or bias: wind and pitot placement are not independently known. Do not change ARSPD_RATIO simply to make the two traces coincide. A successful startup offset calibration is also distinct from calibrating the measurement scale.

ARSPD_USE=0 prevents measured airspeed from controlling automatic throttle. It does not completely isolate the sensor from control: a healthy sensor can still affect stabilization speed scaling. See [ArduPilot airspeed parameters](https://ardupilot.org/plane/docs/airspeed-parameters-setup.html).

## Flight control and mission

- AUTO is the only recorded mode. Movement marker is the first GPS sample at or above 5 m/s, controller time 354.210385 s; this is a launch proxy rather than exact release time.
- Full output, 100% / 1900 microseconds, begins about 2.74 s before the movement marker and persists through takeoff completion. Takeoff completes at controller time 371.050 s, 56.11 m above home; first reaching 60 m occurs about 18.54 s after the movement marker. No initial altitude dip appears in the first three seconds after that marker.
- The selected cruise interval, 381.050–428.650 s, holds altitude within 58.11–60.93 m against the 60 m target. Median throttle command is 61.33%; median groundspeed is 16.09 m/s. Pitch/roll tracking RMS errors are 1.74/3.71 degrees including turns.
- On the matched waypoint-5 leg, altitude is 58.91–60.93 m and pitch/roll tracking RMS errors are 1.41/2.31 degrees. October 9 log 12 had 1.31/1.59 degrees on the corresponding leg. The increase warrants monitoring, but does not by itself justify PID changes; wind and conditions differ, and sensor speed scaling has changed.
- At entry to NAV_LAND there is a brief demanded pitch of -24.71 degrees, followed by actual pitch reaching -21.69 degrees. Much of the maneuver is commanded, with transient tracking lag/overshoot and subsequent pitch/throttle variation on approach. Review the approach geometry and control response if the owner observed an abrupt dive or porpoising. The log does not isolate a tuning fault or sensor cause.
- Flare starts at about 3.0 m, with reported sink 1.37 m/s, speed 15.1 m/s, and target distance 68.7 m. That message's speed must not be substituted for the ARSP measurement. Throttle cuts to idle immediately after flare.
- Disarm is recorded, but there is no automatic-disarm message. Final reported distance from the LAND point is 5.71 m. The LAND target matches log 12; the log does not establish touchdown quality.

Reported peak airspeed exceeds configured AIRSPEED_MAX=22 m/s. With ARSPD_USE=0 and full-throttle takeoff, that parameter is not actively regulating this measured speed or providing a guaranteed speed cap. It is a configuration/operating-envelope review item, not evidence of a sensor failure or a reason to raise the limit blindly. AIRSPEED_MIN=9, CRUISE=12, MAX=22, and STALL=0 remain unvalidated against actual stall and structural limits.

## Other issues

- **Battery current remains invalid for propulsion assessment:** 0.178–0.191 A over the entire log, including full-throttle climb. Voltage ranges 15.78–16.54 V. Capacity and remaining-percentage estimates derived from that current cannot be trusted. With external ESCs, trace whether their power bypasses the AIO current-sensing path before changing calibration factors.
- **Historical relaxed pre-arm settings persist:** ARMING_MAGTHRESH=300 and ARMING_SKIPCHK=4096, plus BATT_ARM_VOLT approximately 13.2 V. These remain a separate preflight configuration review; no settings were changed here.
- GPS has 19–26 satellites, HDOP 0.51–0.73, Status=4 throughout. Both EKF cores have FS=0 and GPS=0.
- Neither IMU clips anywhere in the log. Pre-approach vibration maxima are about 18.49 m/s² on the highest axis, versus about 10.8 in the previous flight; monitor mounting/propeller balance if vibration increases further. No estimator fault is apparent here.

## Next steps

1. Keep ARSPD_USE=0 until completing a dedicated scale-calibration flight and reviewing its results. This flight was approximately two minutes, with AUTOCAL disabled, so it did not carry out the five-minute automatic ratio-calibration procedure.
2. After resolving the existing preflight items, enable ARSPD_AUTOCAL=1 for a controlled flight with repeated turns/circuits for roughly five minutes, retaining ARSPD_USE=0. Land, disable AUTOCAL, refresh/read the resulting ratio, and inspect the new log. Continue loosely shielding the pitot during startup/manual zeroing and remove its cover before flight. [ArduPilot calibration procedure](https://ardupilot.org/plane/docs/calibrating-an-airspeed-sensor.html).
3. Validate suitable speed targets and limits before enabling ARSPD_USE=1 for automatic airspeed/throttle control. That change has not been performed or flight-validated.
4. Correct propulsion-current measurement. Review landing approach behavior if an abrupt dive or oscillation was visible. This review does not support a blanket gain or cruise-throttle increase.

## Artifacts

- [Measured airspeed and control-response plot](../logs/2026-10-13/download-095339_683885/log_00013.airspeed-review.png).
- Metrics: `log_00013.airspeed-review.json` and `log_00013.summary.json` in the same directory.
- Comparison with October 9 flight: `comparison-with-log12.json` in the same directory. GPS speed and throttle changes across days do not isolate sensor integration effects.
- Reproduce with `tools/analyze-flight-log.py`, then `tools/review-airspeed-log.py`, passing the retained BIN path. Parsed `.records.json` files are reproducible and excluded from Git.
