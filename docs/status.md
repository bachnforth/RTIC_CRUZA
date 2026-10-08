# Build status — 2026-10-07

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

## RESOLVED 2026-10-07: MAVLink over ELRS to QGC works (no USB)
- The Pocket's backpack AP is **"ExpressLRS TX Backpack 217F95"** (password `expresslrs`), NOT the plain-named "ExpressLRS TX Backpack" network. The plain-named one belongs to a different radio (also reports "RadioMaster Pocket 2.4GHz TX"); do not join it or send it traffic. Test heartbeats were sent to it by mistake during diagnosis.
- On 217F95 the laptop (Alfa card, "Wi-Fi 2") gets a DHCP lease (10.0.0.10x); the backpack reports `enabled:true`, `gcs` = laptop IP, packets_up and packets_down both climbing.
- QGC link: UDP, local port 14550, server address 10.0.0.1:14555. QGC shows the vehicle (Manual, battery %, RC, GPS) with the AIO on the flight battery and no USB.
- Remaining check: mode switch (channel 7) follows in QGC over this link.
- **The backpack's network name changed** (217F95 -> A3144A) and other ELRS radios are in range, so the saved Wi-Fi profile stopped matching and Windows left the Alfa adapter on 169.254.x.x. Do not trust a fixed SSID.
- **Always run `tools/connect-backpack.ps1`** (normal PowerShell, no admin). It scans for "ExpressLRS TX Backpack *", asks which one is yours, saves a profile if needed, renews DHCP, and prints the backpack's counters.
- **Always confirm the vehicle is yours before using QGC**: flip the channel 7 switch and watch the mode follow. Never arm or send commands until it does. To tell which network is yours, power the Pocket off/on and see which name disappears/returns (scan results can be stale: wait ~60 s).
- If no backpack network is visible: Pocket on and linked ("C"), Backpack > Telemetry toggled Off then WiFi, wait 20 s.
- Idea not yet tested: put the backpack in station mode on the phone hotspot (2.4 GHz) so the name no longer matters; QGC would then use `elrs_txbp.local:14555`.

## Aircraft: Hee Wing T2 Cruza (conventional: ailerons, elevator, rudder; twin motors)
- Servo outputs: S1 aileron (reversed), S4 throttle (ESC), S5 elevator (reversed), S6 rudder; S2/S3 disabled. Directions verified on the bench (props off).
- Accelerometer calibrated; orientation OK (AHRS_ORIENTATION 0, servo rail faces the rear). Compass (BeeID Pro M10, IST8310, connector toward the rear) calibrated; heading matches a phone compass.
- Switches: ch5 RTL (RC5_OPTION 4), ch7 mode (FLTMODE_CH 7: Manual/FBWA/Auto), ch8 ArmDisarm (RC8_OPTION 153).
- Parameter snapshots in `params/` (latest: cruza_params_2026-10-07_1835.params; QGC saves new ones to Documents\QGroundControl\Parameters).
- Config pages in QGC need USB (the radio link does not download the full parameter list).

## Status 2026-10-08 (morning, field test with phone QGC over USB)
- **GPS works** (BeeID Pro M10): fix_type DGPS, 21 satellites, HDOP ~1.2, EKF3 origin set, terrain loaded. Settings that fixed detection (from a classmate with the same hardware): `GPS1_TYPE` u-blox, `GPS_AUTO_CONFIG` disabled, `SERIAL6_BAUD` 115200, `GPS1_RATE_MS` 100, `SERIAL6_OPTIONS` none. A TX/RX swap was tried and was not needed.
- Classmate warns the BeeID relays GPS at ~9.1 Hz, which can make ArduPilot flag the GPS as lagged/unhealthy later; their fallback is a separate GPS (Matek M10Q-5883). Not verified on our aircraft; watch for "GPS unhealthy/lagged" messages.
- `MAV2_PARAMS` = 2 on the ELRS port makes QGC's parameter download over ELRS usable (about 1 minute). ELRS packet rate 500 Hz doubles telemetry bandwidth at some range cost.
- Battery failsafe actions on Plane: `BATT_FS_LOW_ACT`/`BATT_FS_CRT_ACT` = 1 is **RTL** on this firmware (Plane's list is not Copter's). Always use the names shown in QGC, not numbers.
- **Remaining pre-arm failures:** "Check mag field (xy diff:181>100)" and "Gyros inconsistent". Plan: recalibrate compass outdoors away from metal; check whether the BeeID is tilted in its mount (classmate used a custom compass rotation with about 25 degrees pitch); reboot with the plane perfectly still for the gyros.
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
