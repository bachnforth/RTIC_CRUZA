# Cruza airspeed calibration attempt — 2026-10-13

Automatic airspeed calibration ran during log 14, but this was a single AUTO circuit of about two minutes, rather than the recommended five-minute flight with repeated direction changes. The inferred working ratio moved from 2.00 to approximately 1.9295 and was still changing near the end. This is a useful calibration attempt, not sufficient evidence of convergence. Keep ARSPD_USE=0 pending a longer calibration flight and review; do not manually adopt 1.93 as a confirmed final calibration.

## Retrieval and integrity

- Flight: onboard log 14, index timestamp October 13, 2026, 10:19:36 a.m. CDT.
- Downloaded over USB COM17 with the aircraft disarmed; complete live parameter snapshot received, 1245/1245 indexes. No aircraft parameters were changed.
- BIN: `logs/2026-10-13/download-102304_471623/log_00014.BIN`, 6,389,760 bytes, matching the onboard index.
- SHA-256: `c5192bf4e33de04b89385751c1d9424b4ca8c99e915490fcf06103379ccb1613`.
- Parsed BAD_DATA=0 and logger DSF.Dp=0. Live snapshot: `params/cruza_params_2026-10-13_102304_471623_postflight.params`.

## Calibration evidence

The flight's PARM records confirm ARSPD_AUTOCAL=1, ARSPD_USE=0, initial ARSPD_RATIO=2, TYPE=1, BUS=1, DEVID=141321, PSI_RANGE=1, and SKIP_CAL=0. AIRSPEED_CRUISE=15, MIN=10, MAX=22, SCALING_SPEED=15 match the owner's new setup.

| Item | Result |
|---|---|
| Arm to disarm | 125.40 s |
| GPS movement at >=5 m/s to final >=5 m/s sample | 120.02 s; a movement proxy, not exact airborne duration |
| Direction changes | One recorded mission circuit; no extended loiter or repeated circuit before landing |
| Initial working ratio | Approximately 2.0000 |
| Last working ratio with differential pressure >20 Pa | Approximately 1.92948 |
| Overall ratio reduction | Approximately 3.53% |
| Last 30 s of usable pressure samples | Ratio decreases by approximately 0.02043, from 1.94991 to 1.92948 |
| Saved ratio changes / reset messages | None recorded |
| Current controller ratio after reconnect | 2.0000 |
| Sensor health | All 1399 ARSP samples H=1; no unhealthy samples |
| Maximum airspeed sample interval | 0.100911 s |

The working ratio is reconstructed as `ARSP.Airspeed**2 / ARSP.DiffPress`, using samples above 20 Pa to avoid low-pressure numerical sensitivity. In ArduPlane 4.7.1, the MS4525 speed is derived from pressure times ratio, and ARSP logs the raw, unfiltered speed with its corresponding differential pressure. Thus this reconstructs the internal ratio despite the absence of saved PARM changes. See [the exact firmware implementation](https://raw.githubusercontent.com/ArduPilot/ardupilot/Plane-4.7.1/libraries/AP_Airspeed/AP_Airspeed.cpp).

The flight ratio change is less than the firmware's roughly 5% persistence threshold. The calibration code adjusts the working ratio in memory, but only saves sufficiently large changes after its counter threshold; it also emits a ratio-reset message when saving. Therefore an unchanged saved ratio of 2.00 after reconnect is consistent with active calibration making a smaller, unsaved adjustment. It is not evidence that calibration failed to run. See [4.7.1 calibration code](https://raw.githubusercontent.com/ArduPilot/ardupilot/Plane-4.7.1/libraries/AP_Airspeed/Airspeed_Calibration.cpp).

The ratio briefly levels near 1.968 on the long straight leg, then changes again with the later turns and approach. This explains why a single circuit cannot establish a stable final ratio. Wind effects and pitot installation error are not independently measured here.

## Flight and sensor review

- AUTO is the only recorded mode; mission progresses through takeoff, all circuit waypoints, NAV_LAND, flare, and disarm. There is no automatic-disarm message.
- Selected cruise interval is controller time 134.589–181.289 s, omitting early level-off and later descent. Median pitot airspeed is 16.56 m/s, range 14.93–19.03 m/s. Median GPS groundspeed is 14.61 m/s; wind means these need not coincide.
- Cruise altitude ranges 57.73–62.30 m around the 60 m target. Median throttle command is 59.23%. Pitch/roll tracking RMS errors are 2.11/4.15 degrees including turns. Some height, pitch, and throttle variation is visible; this does not establish a sensor-induced control problem.
- ARSP.U remains 0, matching ARSPD_USE=0. This flight does not validate measured-air-speed automatic throttle regulation. A healthy sensor may still affect stabilization speed scaling.
- No ERR records, EKF fault flags (XKF4.FS), or EKF GPS-check flags (XKF4.GPS). GPS has 23–29 satellites.
- Both IMUs have no clipping before landing. A short shock at controller time 228.851 s, coinciding with the landing stop, produces final clipping counts 29/31. Inspect the airframe and pitot attachment if the landing was hard; the timing does not indicate sustained cruise clipping.
- Landing entry again includes a brief steep pitch command: -22.39 degrees demanded, actual minimum -21.00 degrees in the approach window. Flare message: 3.0 m, sink 0.81 m/s, speed 14.9 m/s, distance 65.2 m. Final reported LAND-point distance is 4.93 m. Touchdown quality cannot be established from these figures alone.
- Battery voltage 15.65–16.33 V; current still implausible at 0.188–0.203 A. The previously documented propulsion-current and relaxed arming-check issues remain unresolved.

## Next action

Repeat calibration with ARSPD_AUTOCAL=1 and ARSPD_USE=0, using repeated circuits or circles for roughly five minutes under suitable conditions. The existing takeoff/circuit/landing mission terminates after about two minutes, so repeating that unchanged mission once is insufficient. A longer flight needs a suitable repeated pattern or attended loiter before landing; no mission was edited in this review.

After landing, disable ARSPD_AUTOCAL, read back/export the resulting ratio, and review the new log before enabling ARSPD_USE=1. If the controller is rebooted before a small adjustment was saved, the live ratio may revert to its previous saved value; retain the flight log and obtain a parameter export before power cycling when possible. Do not manually change the ratio solely from this provisional result. [ArduPilot's calibration procedure](https://ardupilot.org/plane/docs/calibrating-an-airspeed-sensor.html).

## Artifacts

- [Airspeed, control response, and reconstructed ratio plot](../logs/2026-10-13/download-102304_471623/log_00014.airspeed-review.png).
- `log_00014.airspeed-review.json`, `log_00014.summary.json`, and original BIN in the same directory. Parsed records are reproducible and excluded from Git.
- Analysis scripts: `tools/analyze-flight-log.py` and `tools/review-airspeed-log.py`.
