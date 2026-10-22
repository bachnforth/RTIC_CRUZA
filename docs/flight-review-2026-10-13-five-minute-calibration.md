# Cruza five-minute calibration flight — 2026-10-13, log 15

The full timed calibration orbit completed and produced a persistent ratio of **1.72559154**, replacing the initial 2.00. Sensor readings remained healthy, navigation/control completed normally, and there were no recorded ERR messages, EKF fault/GPS-check flags, accelerometer clips, or logger drops. However, the ratio still decreased about **2.6% during the final minute of the orbit**. It settled close to the saved value during the subsequent approach, but a steady plateau during sustained circling has not been demonstrated. Treat 1.7256 as the new calibration baseline and verify it with another turning flight before enabling measured-air-speed automatic throttle control.

## Evidence

- Original log: `logs/2026-10-13/download-105658_277326/log_00015.BIN`, 21,168,128 bytes, matching onboard index. Index timestamp October 13, 2026, 10:53:46 a.m. CDT.
- SHA-256: `97b8100d0d9ac8c9ba05415416c2687ea32e2a99ede9a590c86749191d6fa4de`.
- Full parameter snapshot, 1245/1245 indexes: `params/cruza_params_2026-10-13_105658_277326_postflight.params`.
- Downloaded over COM17 with the aircraft disarmed. No vehicle settings were changed. Firmware ArduPlane 4.7.1, dbe79216, TBS_LUCID_H7_WING_AIO.
- Parsed BAD_DATA=0; DSF.Dp=0. Arm-to-disarm duration 451.58 seconds, approximately 7 minutes 32 seconds.

## Mission execution

Log 15 contains a NAV_LOITER_TIME item at sequence 6, commanded duration 300 seconds, altitude 60 m relative to home, clockwise, tangent exit. The recorded center is **33.7245032, -85.9121447**, approximately 73 m west of the generated plan's center; the aircraft flew the uploaded location, not the exact generated preview. Home/takeoff or other mission edits were not assessed as identical to the generated file.

The timed-loiter item starts at controller time 276.998705 s, and `Loiter time complete` is recorded at 585.498697 s. The interval is 308.50 s, including entry and exit-heading completion. Firmware starts the 300-second timer after reaching the orbit. GPS tracking over the final 300 seconds shows approximately **12.16 clockwise turns**, with center-relative radius **58.93–63.98 m**, median **61.22 m**, consistent with WP_LOITER_RAD=60.

The mission then continues to waypoint 7, the 36/16 m approach setup points, NAV_LAND, flare, and disarm. Final reported LAND-point distance is 9.90 m. There is no automatic-disarm message; logs do not establish touchdown quality.

## Ratio calibration

| Evidence | Value |
|---|---:|
| Starting ratio | 2.0000 |
| First saved update, controller time 316.900 s | 1.904373 |
| Second saved update, 410.900 s | 1.812128 |
| Third saved update, 596.900 s, after loiter exit | 1.725592 |
| Current saved/controller value after reconnect | 1.72559154 |
| Ratio range in final 60 s of loiter | 1.777006 → approximately 1.731079 |
| Reduction over that final loiter minute | Approximately 2.58% in ratio, equivalent to about 1.3% in speed scale |
| Last usable pressure sample, controller time 624.900 s | Approximately 1.723246 |
| Final 30 s of usable pressure samples | 1.722096–1.727443; median 1.722888 |

Saved updates appear in both PARM changes and `Airspeed 0 ratio reset` messages. The zero in that message identifies the sensor instance, not its bus. Working ratio between saves is reconstructed from `ARSP.Airspeed² / ARSP.DiffPress` using pressure >20 Pa, according to the 4.7.1 MS4525 raw-speed logging implementation. This is not an independently measured speed calibration.

The saved value is within the usual 1.5–3.0 range described by [ArduPilot's calibration guide](https://ardupilot.org/plane/docs/calibrating-an-airspeed-sensor.html). It represents approximately a 13.72% reduction in the ratio, or a 7.1% reduction in speed scale for the same pressure, versus 2.00. Agreement with the final approach samples supports retaining 1.7256 as a baseline; continued late-orbit movement limits a stronger convergence claim. Do not restore 2.00 or substitute the earlier short-flight estimate of 1.93.

## Sensor and flight health

- All **4663 ARSP samples** have H=1; maximum sample gap 0.101234 s. All U=0, matching ARSPD_USE=0. This flight still does not test airspeed-controlled automatic throttle; a healthy sensor may nonetheless affect stabilization speed scaling.
- Flight settings confirm AUTOCAL=1, SKIP_CAL=0, TYPE=1, BUS=1, DEVID=141321, PSI_RANGE=1. CRUISE=15, MIN=10, MAX=22, SCALING_SPEED=15. No recorded flight changes to these controls apart from automatically saved ratio changes.
- During the selected settled loiter interval, 296.999–585.499 s (first 20 s after command activation omitted), median airspeed is **15.68 m/s**, with 5th–95th percentiles 14.66–17.03 m/s. Working ratio is changing during this interval, so the median is not a fixed-scale reference.
- Final loiter minute: median airspeed **15.06 m/s**, median groundspeed **14.81 m/s**. Wind means those readings need not coincide.
- Settled-loiter altitude **57.85–62.50 m**, median 59.97 m, against 60 m target. Pitch/roll tracking RMS **1.44/2.14 degrees**, including the continuous bank. Median commanded throttle 62.10%.
- GPS 27–32 satellites, HDOP 0.45–0.59; both EKF cores have FS=0, GPS=0. No ERR records. No accelerometer clipping anywhere in the log.
- Sensor temperature ranges 25.65–28.88 C. Flight offset is 59.9561 Pa; live post-reconnect offset 59.9771 Pa. Startup sheltered calibration conditions are not established by an armed-flight log.
- Battery voltage **15.35–16.12 V**. Current remains implausible at **0.192–0.207 A**, so propulsion consumption and remaining-capacity indications remain invalid.
- Historical ARMING_MAGTHRESH=300 and ARMING_SKIPCHK=4096 remain in the postflight snapshot; previous preflight review items have not been resolved by this sensor calibration.

## Recommendation

Retain **ARSPD_RATIO=1.7256** as the saved baseline. Keep **ARSPD_USE=0** for a confirmation flight with repeated turns starting from this baseline. If repeating calibration, retain **ARSPD_AUTOCAL=1** for that flight and review whether the ratio becomes stable through its final circles, rather than only after leaving the orbit. A repeat need not start from 2.00.

After a satisfactory confirmation, set **ARSPD_AUTOCAL=0**, preserve/read back the calibrated ratio, and then validate **ARSPD_USE=1** in a controlled automatic-speed flight. CRUISE=15 is close to the last loiter minute's reading, but MIN=10 is still not a proven stall margin. This log does not establish stall speed, structural speed limits, or full-aircraft readiness. No setting changes were performed during this review.

## Artifacts

- [Airspeed and reconstructed ratio plot](../logs/2026-10-13/download-105658_277326/log_00015.airspeed-review.png).
- Metrics: `log_00015.airspeed-review.json`, `log_00015.summary.json`, and full original BIN in the same directory. Parsed records are reproducible and excluded from Git.
- Reproduce with `tools/analyze-flight-log.py` and `tools/review-airspeed-log.py`.
