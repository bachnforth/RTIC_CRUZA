# Cruza AUTO test flight — 2026-10-09

Retrieved over USB from the TBS Lucid Wing AIO on COM17, running ArduPlane 4.7.1 (dbe79216). The three newest onboard logs were copied without erasing or modifying them. Download sizes match the onboard log index; SHA-256 values are recorded below. Log 9 contains the AUTO test flight; logs 8 and 7 contain ground activity.

## Files and changes

- Flight: `logs/2026-10-09/log_00009.BIN` (10,551,296 bytes).
- Ground logs: `log_00008.BIN` (1,179,648 bytes), `log_00007.BIN` (655,360 bytes).
- Plot: `logs/2026-10-09/log_00009.png`; parsed records and summaries sit beside each log.
- Before-change USB parameters: `params/cruza_params_2026-10-09_postflight.params`.
- After-change parameters: `params/cruza_params_2026-10-09_cruise54.params`.
- **Applied and independently read back: TRIM_THROTTLE 45 → 54**, interpreting the owner's requested roughly 20% cruise increase as a relative increase in the trim setting. This does not guarantee a 20% increase in thrust, speed, or actual flight throttle. Revert by setting TRIM_THROTTLE to 45.
- Takeoff settings, ESC endpoints, mission, gains, arming settings, and sensor settings were not changed. No arming, motor tests, or mode changes were commanded.

## Takeoff finding

The owner reports a weak AUTO launch. The flight log shows AUTO triggered about 0.2 s after arming while stationary (GPS speed 0.0 m/s). Throttle ramped to its configured maximum in approximately 1 s, before the acceleration consistent with release around four seconds after arming. It remained at **CTUN.ThO=100% and RCOU.C4=1900 µs** through the takeoff climb. The mission specified 10° minimum pitch and a 60 m relative takeoff altitude; takeoff completed around 22.7 s after arming.

TKOFF_THR_MAX=0 inherits THR_MAX=100, so changing TKOFF_THR_MAX to 100 would have the same effect. TKOFF_THR_SLEW=0 inherits THR_SLEWRATE=100%/s. A faster ramp would not address this recorded launch because full output was already reached before release. TKOFF_THR_MAX_T=4 is not the duration of full takeoff throttle under these settings: the log confirms full throttle through the climb.

SERVO4_MIN/MAX are 1100/1900 µs. These are the controller's configured endpoints, not proof of the ESC's calibrated endpoints or of actual maximum motor power. To obtain more physical launch thrust, first establish the ESC endpoint calibration and battery/motor/propeller configuration. Do not expand PWM endpoints or change battery voltage without that evidence. The log records a small initial loss of height after release before a sustained climb; it does not identify the propulsion limitation or a stall.

TKOFF_THR_MINACC and TKOFF_THR_MINSPD are both zero. This flight triggered motor start while stationary, rather than detecting a throw. Review the launch procedure and detection settings separately; they were not changed during this review.

## Cruise and control response

During a representative level cruise window (controller time 470–559 s), altitude was 58.79–61.16 m above home with a median of 59.91 m. Actual throttle was 51.14–67.30%, median 58.90%. Pitch and turn compensation explain why output can exceed the old 45% trim: with no enabled airspeed sensor, ArduPlane calculates throttle using the trim plus pitch and bank compensation. The increased trim is a new baseline for the next controlled test, not a flight-validated setting.

GPS groundspeed in that window was 7.50–14.28 m/s, median 10.89 m/s. This is not measured airspeed; ARSPD_TYPE=0 and TECS_SYNAIRSPEED=0. AIRSPEED_CRUISE=12 alone cannot provide measured closed-loop airspeed control with this setup.

Roll/pitch broadly track demanded attitude. RMS tracking errors over the same cruise window were 2.64° roll and 1.98° pitch. Those figures are descriptive, not a diagnosis or enough to prescribe new PID gains. The log shows pitch disturbances; an additional FBWA/AUTOTUNE flight with controlled inputs and known trim/CG would support gain tuning. No gain changes were made from this AUTO circuit.

The flight progressed through waypoint 8 and NAV_LAND, recorded a flare, then automatically disarmed. No ERR records were parsed. This establishes a completed logged AUTO sequence, not a full assessment of landing quality.

## Sensor and configuration observations

- AHRS_ORIENTATION=6, SERVO5_REVERSED=0, RC2_REVERSED=1 match the prior bench corrections.
- GPS during the log reports 28–32 satellites and HDOP 0.45–0.53, with 3D/DGPS fixes.
- Battery voltage reported 16.02–16.50 V, but current stayed 0.193–0.208 A through a powered flight and reported only about 13 mAh used. The current readings are implausible for the propulsion load; wiring/pin/calibration needs verification before using current, consumed capacity, or inferred battery resistance to assess propulsion. Voltage calibration was not independently checked here.
- ARMING_MAGTHRESH=300, ARMING_SKIPCHK=4096, and BATT_ARM_VOLT≈13.2 remain in the USB snapshot. The workspace previously identified these as temporary settings needing review; they were not altered as part of the throttle request.

## Owner hardware clarification and next propulsion check

The owner confirms the motors and propellers are those supplied with the Cruza kit; ESC endpoint calibration history is unknown. Battery is confirmed 4S / 14.8 V. The owner corrected the earlier description of using the AIO's built-in ESC: the motors connect to the original aircraft ESCs, which connect to the AIO for throttle control. The single built-in AIO ESC is not driving both motors. No further propulsion settings were changed.

The manufacturer's current [T2 PNP manual](https://www.heewing.com/pages/t2-instruction-manual) specifies a 6S LiPo setup. The owner confirms a 4S pack, consistent with the flight voltage around 16 V. Running a propulsion system intended for 6S on 4S is a plausible contributor to reduced launch power, not a confirmed diagnosis. Kit revisions may differ. Verify all installed electronics and their power connections before switching to a higher-voltage pack.

The [current product listing](https://www.heewing.com/products/t2-cruza-pnp) and the linked assembly manual list different motor/propeller configurations (3110/10-inch versus 2216/8060), so exact motor and prop specifications cannot be established from “stock kit” alone. Both specify 6S batteries.

ArduPilot's [Plane ESC calibration guidance](https://ardupilot.ardupilot.org/plane/docs/common-esc-calibration.html) explains that PWM ESCs may need endpoint calibration, whereas digital protocols such as DShot do not. Calibration requires both propellers removed and a coordinated power-up/throttle sequence; no such sequence was performed remotely.

Heewing's [FX-25A ESC page](https://www.heewing.com/products/fx-25a), which identifies the ESC for T2 Cruza/F01, supplies a maximum-then-minimum throttle calibration procedure. The next check is to teach both original ESCs the existing 1100–1900 µs range, with props removed, aircraft in MANUAL, and the controller/receiver operating on USB before applying ESC battery power. Verify RC input remains available with the battery disconnected before attempting that sequence. Successful calibration would make 1900 µs the learned maximum; it does not overcome a limitation from battery voltage.

### Calibration result

Performed an attended calibration sequence with both propellers removed per owner confirmation. Verified MANUAL and RC switch response on USB. Owner armed at low throttle, and MAVLink confirmed 1100 µs. Owner then raised throttle, and telemetry confirmed steady 1900 µs before the ESC battery-power step. Owner subsequently reported two distinct "Di Di" sounds, consistent with both ESCs accepting the low endpoint after the high endpoint. After restoration of the battery monitor and normal ESC power-up, the owner confirmed both motors started and ran smoothly. Final telemetry confirms disarmed MANUAL, 1100 µs output, and restored battery parameters. ESC memory was not independently read; actual thrust increase and flight performance have not yet been measured.

For USB-only preparation, battery arming threshold and battery failsafe actions were briefly set to zero, but the previously latched battery failsafe still blocked the pre-arm check. All three were restored. BATT_MONITOR was then temporarily disabled and the controller rebooted. A transient startup gyro warning cleared on a later pre-arm check; no gyro check was bypassed. After the owner's calibration report, telemetry confirmed disarmed MANUAL and low throttle. BATT_MONITOR=4 was restored, the controller rebooted again, and a fresh full parameter export verified BATT_ARM_VOLT≈13.2, both battery failsafe actions=1, TRIM_THROTTLE=54, and unchanged 1100/1900 endpoints. No temporary calibration overrides remain. See `logs/2026-10-09/esc-calibration-result.json` and `params/cruza_params_2026-10-09_post_esc_calibration.params`.

Because the original external ESCs drive the motors, the very low logged current might reflect only electronics current if propulsion power bypasses the AIO's sensing path. Trace battery distribution before assuming that recalibration alone can make the onboard current monitor measure both motors.

## Integrity

| Log | SHA-256 |
|---|---|
| 9 | `873c7eb4609eae4fe128757fa9460f2892a9029d9472327b043c903ac5be91cd` |
| 8 | `cbb0f3379a7b904f4c675be684c71e4801fca4c298b7f5837cf658142d43ad58` |
| 7 | `8f81abe1ecec1f8bda0c752102da07fe652c6f062746a0d98de776344e1b73b8` |

## Firmware references

- [ArduPlane 4.7.1 takeoff throttle limits](https://github.com/ArduPilot/ardupilot/blob/Plane-4.7.1/ArduPlane/takeoff.cpp).
- [ArduPlane 4.7.1 throttle slew handling](https://github.com/ArduPilot/ardupilot/blob/Plane-4.7.1/ArduPlane/servos.cpp).
- [ArduPlane 4.7.1 throttle without airspeed](https://github.com/ArduPilot/ardupilot/blob/Plane-4.7.1/libraries/AP_TECS/AP_TECS.cpp).
- [ArduPilot automatic takeoff](https://ardupilot.org/plane/docs/automatic-takeoff.html).
- [ArduPilot AUTOTUNE](https://ardupilot.org/plane/docs/automatic-tuning-with-autotune.html).
