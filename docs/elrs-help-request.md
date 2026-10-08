**ELRS MAVLink over TX backpack Wi-Fi: backpack never registers the GCS (enabled:false, gcs "IP UNSET")**

> Resolved 2026-10-08. The plain SSID was firmware-update mode, while
> `Backpack > Telemetry = WiFi` starts the MAVLink service and suffixed AP. The
> Pocket now has a fixed-UID Backpack 1.5.9 image and stable SSID. See
> `docs/elrs-backpack.md` for the resolution, firmware, and verified behavior.

**Hardware**
- Transmitter: RadioMaster Pocket (internal 2.4 GHz ELRS module, EdgeTX)
- Receiver: BETAFPV SuperD 2.4 GHz (target Unified_ESP32_2400_RX)
- Flight controller: TBS Lucid Wing AIO, ArduPilot Plane stable (target TBS_LUCID_H7_WING_AIO), receiver on UART4 / SERIAL4
- GCS: QGroundControl 5.1.4 on Windows 11

**Versions**
- Pocket module: ELRS 3.6.4
- Pocket TX backpack: 1.5.9
- Receiver: ELRS 3.5.6 (an update from 3.3.0 to 3.6.4 over Wi-Fi failed twice with "Update Failed"; 3.5.6 worked)

**Settings**
- Pocket Lua: Link Mode = MAVLink (set with the RX unpowered; ELRS refuses while connected), Backpack > Telemetry = WiFi. Both survive a power cycle.
- Receiver Lua: Protocol = MAVLink, Target SysID 1, Source SysID 255, Tlm Power 100 mW
- ArduPilot: SERIAL4_PROTOCOL=2, SERIAL4_BAUD=460, RSSI_TYPE=5

**What works**
- RC over the link works in MAVLink mode (sticks move in QGC, the 3-position switch still gives 3 values)
- MAVLink data from the aircraft reaches the backpack

**The problem**
QGC never connects through the backpack's Wi-Fi. The backpack's own status page (http://10.0.0.1/mavlink, laptop joined to the plain-named "ExpressLRS TX Backpack" AP, DHCP lease 10.0.0.100) reports:

    {"enabled":false,"counters":{"packets_down":5792,"packets_up":0,"drops_down":4,"overflows_down":361},"ports":{"listen":14555,"send":14550},"ip":{"gcs":"IP UNSET"},"protocol":"UDP"}

- /config reports mode "AP" and product_name "RadioMaster Pocket 2.4GHz TX"
- packets_down keeps climbing; packets_up stays 0; gcs ip stays unset
- Nothing arrives on UDP 14550 on the laptop (listened for 8 s)

**What I tried**
- QGC UDP link: local port 14550, server address 10.0.0.1:14555 (verified in the saved QGC config), UDP AutoConnect off
- Sent valid MAVLink 1 and MAVLink 2 heartbeats (sysid 255, compid 190) from the laptop to 10.0.0.1:14555, including from source port 14550. The backpack did not register them.
- Power-cycled the Pocket and relinked; counters reset, same result
- Windows firewall has inbound allow rules for QGC on the Public profile
- Static IP vs DHCP on the laptop's adapter made no difference

**Questions**
1. What makes the backpack's MAVLink `enabled` flag true?
2. What triggers the backpack to learn the GCS IP: a specific MAVLink message, a source port, or a config step?
3. Does an internal-module Pocket need anything beyond Link Mode = MAVLink and Telemetry = WiFi?

Next step on my side: try the backpack in station mode on a phone hotspot.
