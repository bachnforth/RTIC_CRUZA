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

## History of the problem (kept for reference)
- Backpack AP is the plain-named "ExpressLRS TX Backpack" (identifies as "RadioMaster Pocket 2.4GHz TX"), IP 10.0.0.1.
- Status page: `http://10.0.0.1/mavlink` -> `enabled:false`, `gcs: "IP UNSET"`, listen 14555, send 14550.
- `packets_down` climbs (aircraft data reaches the backpack), `packets_up` stays 0, nothing reaches the laptop on UDP 14550.
- QGC link: UDP, local port 14550, server 10.0.0.1:14555 (verified in QGroundControl.ini). Test heartbeats (MAVLink 1 and 2) sent to 10.0.0.1:14555 did not register either.
- Not yet tried: backpack in STA mode on a home network; Tlm Power -> matchTX; asking the ELRS Discord.

## Other
- Alfa AWUS (Realtek 8812AU) is "Wi-Fi 2"; DHCP re-enabled on it. Receiver Wi-Fi mode did not hand out DHCP leases to the laptop; phone upload worked.
- Still to do: accelerometer + compass calibration, airspeed sensor, servo/elevon outputs, failsafes, traffic-pattern mission.
