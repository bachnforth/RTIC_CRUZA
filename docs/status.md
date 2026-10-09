# Build status — 2026-10-08

## Airspeed sensor newly connected — 2026-10-09

- Owner reports installing an airspeed sensor and connecting it to the AIO after the second AUTO flight. Sensor model, bus wiring, detection, and calibration have not yet been verified.
- Read-only live USB check after installation confirms ARSPD_TYPE=0 and ARSPD_USE=0. The sensor driver remains disabled, so a physical connection alone does not provide measured airspeed records. Existing airspeed estimates must not be presented as readings from the new sensor.
- No vehicle parameters were changed during this check. Configure the correct sensor type/bus and verify/calibrate readings before using sensor data for flight control. ARSPD_USE=0 does not by itself guarantee complete isolation from flight control: a configured healthy sensor may still be used for speed scaling, as described in [ArduPilot's airspeed parameter documentation](https://ardupilot.org/plane/docs/airspeed-parameters-setup.html).

## Second AUTO flight reviewed — 2026-10-09

- Owner reports the same method/equipment/conditions and that everything worked well. Log 12 confirms AUTO takeoff, circuit, NAV_LAND/flare, and disarm. [Second-flight report and comparison](flight-review-2026-10-09-second-flight.md).
- First reaching 60 m after the GPS movement marker improved from 18.34 s to 14.26 s (~22% sooner); the earlier initial height dip was absent in new samples. Full takeoff output remained 100% / 1900 µs in both flights.
- On the same long cruise leg, median groundspeed increased 10.93 → 14.30 m/s and median throttle fell 58.94% → 50.03%. Pitch tracking improved and straight-leg roll tracking was similar. Broader cruise/turn roll error increased; no gains were changed.
- LAND target moved 35.8 m. Final recorded distance to the new target was 3.70 m, so the landing distances are not directly comparable against an identical target. Log 12 records disarm, but not an automatic-disarm message.
- Retain TRIM_THROTTLE=54, existing gains, and calibrated 1100–1900 µs endpoints as the new baseline. No vehicle settings were changed during this log review. Sensor/current-monitor and historical arming-setting review items remain as documented below.

## AUTO test flight and log review — updated 2026-10-09

**ESC endpoint calibration and normal startup check completed:** Both props removed and USB-only preparation confirmed by owner. Owner armed in MANUAL; telemetry verified 1100 µs at low stick and steady 1900 µs at full stick before ESC power-up. Owner reports two distinct "Di Di" confirmation sounds after lowering throttle, consistent with both original ESCs accepting the endpoints. After battery monitor restoration and normal ESC power-up, owner confirmed both motors started and ran smoothly. Final telemetry confirms disarmed MANUAL and 1100 µs throttle. Temporary battery changes were all restored, controller rebooted, and values read back: BATT_MONITOR=4, BATT_ARM_VOLT≈13.2, BATT_FS_LOW_ACT=1, BATT_FS_CRT_ACT=1. No temporary calibration overrides remain; the historical 13.2 V arming threshold is still pending the separate review noted below. Cruise trim remains 54. Saved complete controller export to `params/cruza_params_2026-10-09_post_esc_calibration.params`. ESC memory was not read directly; increased physical thrust and flight improvement remain unverified. Motors were controlled by the owner; no remote arming or motor-output commands were sent.

- Retrieved the three newest onboard logs over USB; log 9 contains the AUTO takeoff, circuit at approximately 60 m, and NAV_LAND/automatic disarm. Saved logs, plots, parameter snapshots, and findings in [flight review](flight-review-2026-10-09.md).
- Fresh USB settings confirm AHRS_ORIENTATION=6, SERVO5_REVERSED=0, RC2_REVERSED=1. This test supplies flight evidence after the earlier bench corrections; the older pending checklist below is retained as history and does not establish which individual checks the owner completed.
- Owner reported weak takeoff and requested roughly 20% more cruise thrust. Takeoff already used 100% throttle / 1900 µs before release and throughout the climb. More physical takeoff power requires verifying ESC endpoints and propulsion hardware; takeoff parameters were not changed.
- Applied TRIM_THROTTLE 45 → 54 (20% relative increase in cruise trim), verified by independent MAVLink readback while the aircraft was disarmed. New setting has not been flight-tested. Before/after exports are in `params/`.
- Current monitoring is implausible (~0.2 A throughout flight); verify the sensor connection/configuration/calibration. Airspeed sensor remains disabled. Temporary arming settings still need review.
- Owner confirms 4S / 14.8 V battery and stock kit motors/propellers/original aircraft ESCs. The original ESCs receive throttle control from the AIO; its built-in ESC is not driving both motors. ESC endpoint calibration history is unknown. Check endpoint calibration with props removed; manufacturer documentation specifies 6S for the stock propulsion setup, so the confirmed 4S pack is a potential contributor to weak takeoff power.

## Current flight-control corrections — updated 2026-10-09

- Failed launch on 2026-10-08: owner reports an immediate nose dive in AUTO with motors running. Bench investigation found swapped attitude axes and reversed elevator stabilization.
- Confirmed owner-applied settings: **AHRS_ORIENTATION=6 (Yaw270)**, **SERVO5_REVERSED=0 (Normal)**, **RC2_REVERSED=1 (Reversed)**. The AIO is mounted upright across the fuselage.
- Nose-down ATTITUDE now reports negative pitch with roll near zero. Owner confirms FBWA nose down -> elevator UP; nose up -> elevator DOWN; right wing down -> right aileron DOWN/left UP. Pull-back now moves elevator UP.
- Recalibration, final attitude/control checks in both directions, final stick checks in FBWA and MANUAL, crash inspection, CG check, and a controlled FBWA checkout remain pending. These bench corrections have not been flight-validated.
- Existing full parameter snapshots predate these changes. Save a new export; do not treat the historical orientation/reversal notes below as the current setup.
- Details and remaining checks: [launch investigation](launch-investigation-2026-10-08.md).

## Current GPS hardware — updated 2026-10-08
- Replaced the NewBeeDrone BeeID Pro M10 with a **Mateksys M10Q-5883** (owner-confirmed hardware swap).
- Post-swap wiring, GPS configuration, compass detection/orientation/calibration, and GPS fix/health results have not yet been recorded.
- Existing `params/` snapshots are retained as pre-swap records; no post-swap parameter export is available yet. The BeeID settings and calibration results below describe the previous hardware and are not a verified M10Q-5883 configuration.

## Done
- AIO (TBS Lucid Wing AIO) flashed with ArduPilot Plane stable, target `TBS_LUCID_H7_WING_AIO` (via STM32 DFU + with_bl hex; QGC could not enter the bootloader). Files in `firmware/`.
- QGC 5.1.4 connects over USB (ArduPilot MAVLink port). Radio calibrated.
- RC over ELRS works with the receiver in MAVLink mode (sticks move; channel 7 gives 3 positions).
- Flight modes: mode channel 7 -> slot1 Manual, slot4 FBWA, slot6 Auto (slot5 Auto). Channel 5 -> RTL (RC5_OPTION=4).
- AIO params for MAVLink-over-ELRS: SERIAL4_PROTOCOL=2, SERIAL4_BAUD=460, RSSI_TYPE=5. SERIAL4 = UART4 = receiver (RC input).
- ELRS versions: Pocket module 3.6.4, Pocket backpack 1.5.9 (latest), receiver (BETAFPV SuperD 2.4G) 3.5.6.
  - Receiver update to 3.6.4 failed twice over Wi-Fi ("Update Failed"); 3.5.6 succeeded.
  - Binding phrase used on the module and receiver builds (same on both): `PrairieKite-ELRS-7426`
- Pocket settings: Link Mode = MAVLink (set with the receiver unpowered; ELRS refuses while linked), Backpack Telemetry = WiFi.

## RESOLVED 2026-10-08: MAVLink over ELRS to QGC works (no USB)
- The Pocket backpack now runs a custom 1.5.9 image with a fixed UID. Its stable AP is **"ExpressLRS TX Backpack 456B22"** (password `expresslrs`). Firmware and recovery instructions are in `firmware/` and `docs/elrs-backpack.md`.
- The plain-named "ExpressLRS TX Backpack" network is firmware-update mode, not the normal MAVLink AP. `Backpack > Telemetry = WiFi` starts the MAVLink AP; do not use the separate "Enable Backpack WiFi" command for normal operation.
- The laptop (Alfa card, "Wi-Fi 2") gets a DHCP lease in 10.0.0.0/24; the backpack reports `enabled:true` and learns the laptop's GCS IP from the first UDP datagram sent to port 14555.
- QGC link: UDP, local port 14550, server address 10.0.0.1:14555. QGC shows the vehicle (Manual, battery %, RC, GPS) with the AIO on the flight battery and no USB.
- Remaining check: mode switch (channel 7) follows in QGC over this link.
- The earlier stock image changed suffix (217F95 -> A3144A), which broke the saved Windows profile. The fixed-UID image was cold-boot tested: 456B22 returned and Windows reconnected automatically.
- `tools/connect-backpack.ps1` now defaults to the fixed 456B22 AP, retains scan fallback, renews DHCP if necessary, and prints the backpack's counters.
- **Always confirm the vehicle is yours before using QGC**: flip the channel 7 switch and watch the mode follow. Never arm or send commands until it does. The fixed 456B22 suffix identifies this Pocket, but the control check remains mandatory.
- If no backpack network is visible: Pocket on and linked ("C"), Backpack > Telemetry toggled Off then WiFi, wait 20 s.
- Station mode on a phone hotspot is no longer needed to stabilize the network name.

## Aircraft: Hee Wing T2 Cruza (conventional: ailerons, elevator, rudder; twin motors)
- Servo outputs: S1 aileron (reversed), S4 throttle (ESC), S5 elevator (reversed), S6 rudder; S2/S3 disabled. Directions verified on the bench (props off).
- Accelerometer calibrated; orientation OK (AHRS_ORIENTATION 0, servo rail faces the rear). Previous compass (BeeID Pro M10, IST8310, connector toward the rear) was calibrated and its heading matched a phone compass; replacement sensor verification is pending as noted above.
- Switches: ch5 RTL (RC5_OPTION 4), ch7 mode (FLTMODE_CH 7: Manual/FBWA/Auto), ch8 ArmDisarm (RC8_OPTION 153).
- Parameter snapshots in `params/` (latest: cruza_params_2026-10-07_1835.params; QGC saves new ones to Documents\QGroundControl\Parameters).
- Config pages in QGC need USB (the radio link does not download the full parameter list).

## Historical status 2026-10-08 (morning, BeeID field test with phone QGC over USB, before GPS swap)
- **GPS works** (BeeID Pro M10): fix_type DGPS, 21 satellites, HDOP ~1.2, EKF3 origin set, terrain loaded. Settings that fixed detection (from a classmate with the same hardware): `GPS1_TYPE` u-blox, `GPS_AUTO_CONFIG` disabled, `SERIAL6_BAUD` 115200, `GPS1_RATE_MS` 100, `SERIAL6_OPTIONS` none. A TX/RX swap was tried and was not needed.
- Classmate warned the BeeID relays GPS at ~9.1 Hz, which can make ArduPilot flag the GPS as lagged/unhealthy later; their fallback was a separate GPS (Matek M10Q-5883). Our aircraft now has that replacement model installed; post-swap GPS health results have not yet been recorded.
- `MAV2_PARAMS` = 2 on the ELRS port makes QGC's parameter download over ELRS usable (about 1 minute). ELRS packet rate 500 Hz doubles telemetry bandwidth at some range cost.
- Battery failsafe actions on Plane: `BATT_FS_LOW_ACT`/`BATT_FS_CRT_ACT` = 1 is **RTL** on this firmware (Plane's list is not Copter's). Always use the names shown in QGC, not numbers.
- **Remaining pre-arm failures:** "Check mag field (xy diff:181>100)" and "Gyros inconsistent". Plan: recalibrate compass outdoors away from metal; check whether the BeeID is tilted in its mount (classmate used a custom compass rotation with about 25 degrees pitch); reboot with the plane perfectly still for the gyros.
- **Pre-flight diagnostic 2026-10-08 10:33/10:47 (params in `params/`):**
  - Compass recalibrated; `COMPASS_ORIENT` changed from Roll180 to Pitch180 (a half-turn in yaw), scale factors uneven (0.94/0.99/0.91). **Redo the heading check against a phone compass.** `COMPASS_LEARN` is EKF-Learn (was Disabled): set back to Disabled. Is the BeeID tilted? Not yet answered.
  - `ARMING_MAGTHRESH` raised to 300 (default 100) hides the mag-field check: set back to 100 and retest.
  - `ARSPD_TYPE` set to None (no sensor), as of 10:47. Flying without airspeed: fly conservatively.
  - Do **not** use Auto takeoff on the maiden (`TKOFF_THR_MINACC` is 0, no launch detection). Hand-launch in FBWA.
  - Mission has 9 items (`MIS_TOTAL`), not yet reviewed. `WP_RADIUS` 90 m and `NAVL1_PERIOD` 17 are generous for a 1.2 m plane.
  - Geofence is off; consider a 300 m circle / 100 m altitude fence with RTL.
  - Confirm a microSD card is in the AIO (logging and terrain need it). RC-loss failsafe and ELRS range check still to be tested. CompassMot / heading under throttle not checked.
- **Temporary / unsafe-for-flight settings to revert before flight:**
  - `ARMING_SKIPCHK` = 4104 (skips GPS lock and GPS configuration checks). Untick GPS lock now that there is a real fix.
  - `BATT_ARM_VOLT` = 13.2 (set back to 15.0 with a full pack).
  - `ARMING_MAGTHRESH` must stay 100 for flight (only raise temporarily for a bench motor test).

## BEFORE FIRST FLIGHT (temporary bench settings to revert)
- `BATT_ARM_VOLT` is temporarily **13.2** (bench only). Set back to **15.0** (4S: 3.75 V/cell) before flight, with a pack charged to 16.8 V.
- Battery: HRB 4S 4000 mAh. `BATT_VOLT_MULT` 20.7 verified (QGC 16.69 V vs multimeter 16.73 V). `BATT_CAPACITY` 4000. Low 14.0 V / critical 13.2 V; both actions should be 2 (RTL) until a landing sequence exists.
- RC loss: `FS_LONG_ACTN` 1 (RTL). `RTL_AUTOLAND` 0 until the mission has a landing sequence.

## TODO (priority order)
1. ESC/motor check with the propeller off, then set the ESC range if needed (SERVO4 min/max 1100/1900 now).
2. Failsafes: RC loss, low battery, GPS loss; ARMING_RUDDER -> 0 so only ch8 arms.
3. Verify the battery monitor against a multimeter (BATT_MONITOR 4, VOLT_MULT 11, AMP_PERVLT 40, CAPACITY 3300 look like defaults).
4. Traffic pattern mission (Plan view) and a bench Auto test.
5. LOW PRIORITY, parked: airspeed sensor. ARSPD_TYPE 1 (MS4525), ARSPD_BUS 1, ARSPD_DEVID 0 = sensor not detected; needs 5V/GND/SCL/SDA on I2C1 (PB6/PB7). Do not plug an I2C sensor into the CAN connector. ARSPD_USE stays 0 until it reads sensibly.

## History of the problem (kept for reference)
- Backpack AP is the plain-named "ExpressLRS TX Backpack" (identifies as "RadioMaster Pocket 2.4GHz TX"), IP 10.0.0.1.
- Status page: `http://10.0.0.1/mavlink` -> `enabled:false`, `gcs: "IP UNSET"`, listen 14555, send 14550.
- `packets_down` climbs (aircraft data reaches the backpack), `packets_up` stays 0, nothing reaches the laptop on UDP 14550.
- QGC link: UDP, local port 14550, server 10.0.0.1:14555 (verified in QGroundControl.ini). Test heartbeats (MAVLink 1 and 2) sent to 10.0.0.1:14555 did not register either.
- Not yet tried: backpack in STA mode on a home network; Tlm Power -> matchTX; asking the ELRS Discord.

## Other
- Alfa AWUS (Realtek 8812AU) is "Wi-Fi 2"; DHCP re-enabled on it. Receiver Wi-Fi mode did not hand out DHCP leases to the laptop; phone upload worked.
- Still to do: accelerometer + compass calibration, airspeed sensor, servo/elevon outputs, failsafes, traffic-pattern mission.
