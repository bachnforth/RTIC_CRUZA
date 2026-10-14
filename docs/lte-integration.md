# LTE integration — 2026-10-13

## Pi LTE and private-network verification — 2026-10-14

- Corrected USB topology: owner removed cable from Pi data socket to HAT
  downstream USB1. Stacked pogo connection then enumerated hub 1a40:0101 and
  modem 1e0e:9001. USB1/USB2 are peripheral ports, not inputs from the Pi.
- ModemManager detects SIM7600G-H, firmware LE20B04SIM7600G22, with qmi_wwan
  and option drivers. AT&T LTE roaming registration; signal quality 67.
- Owner activated NetworkManager `cruza-lte`, APN america.bics; data interface
  wwan0. IPv4 100.80.66.223/26, gateway 100.80.66.224, DNS 8.8.8.8/8.8.4.4.
  Address is within carrier shared-address space, so private VPN remains required.
- LTE-bound ping: 3/3 replies, 61–243 ms in this small sample. LTE-bound HTTPS
  to example.com returned 200 with local address 100.80.66.223. A DNS query
  explicitly bound to wwan0 returned a valid response from 8.8.8.8.
- Disconnected Pi Wi-Fi with an independently scheduled 90-second restoration.
  Private SSH to Pi 100.100.0.58 succeeded while wlan0 was disconnected and
  wwan0 was the sole default route. Pi reached Android 100.100.0.57 via relay,
  153 ms in one probe. This verifies Headscale access over LTE through NAT.
- Timed restoration successfully reconnected RN08. Wi-Fi remains preferred
  at metric 600; LTE at 700. LTE autoconnect=yes, retries=0 (unlimited).
- Controlled recovery: disconnected modem bearers with mmcli; NetworkManager
  automatically reactivated cruza-lte. Subsequent LTE-bound HTTPS returned 200.
  This is one session-disruption test, not prolonged coverage-loss validation.
- Usage monitoring is sampling wwan0 and persists approximate counters. Sample
  cumulative estimate was 151,029 bytes, not carrier-billed usage. No throttling
  flags reported during these tests. No aircraft commands or FC changes made.

LTE connectivity is now verified on the Pi. AIO UART reception, actual Android
video reception, combined traffic/resource tests and controlled flight testing
remain incomplete. See [Pi audit](pi-companion-audit-2026-10-14.md).

## Hardware

- Waveshare SIM7600G-H 4G HAT (B), SKU 19485.
- EIOTCLUB USA dual-network AT&T/T-Mobile data SIM; packaging says 24 GB/year. Account balance and expiration not checked.
- Planned companion computer: Raspberry Pi Zero 2 W (owner confirmed).
- MAIN LTE antenna attached; HAT connected to Windows laptop by USB.

## Verified laptop bench test

- Windows initially detected USB VID_1E0E/PID_9001 but six interfaces lacked drivers (error 28).
- Driver package downloaded from the exact HAT's Waveshare wiki. Its installer unpacked files; direct elevated pnputil installation of the win10 INF files completed device attachment. Driver catalogs had valid Microsoft Windows Hardware Compatibility Publisher signatures.
- All seven SIMCOM parent/interface devices subsequently reported OK.
- AT port at test time: COM19. Other ports: diagnostics COM18, audio COM20, NMEA COM22. Ports may change after reconnecting.
- SIM ready; LTE registration reported roaming, operator T-Mobile BICS, LTE band 4. Signal query CSQ=17,99.
- SIM prefix matched EIOTCLUB's 893204 instructions. Full SIM identifiers are intentionally omitted.
- Changed data context 1 from IP/CMNET to IP/america.bics and verified readback. Contexts 2 and 3 left unchanged.
- Started modem data session with AT$QCRMCALL=1,1; received successful IPv4 response and a Windows Cellular IPv4 address.
- Three pings explicitly bound to the cellular IPv4 address succeeded (86–115 ms, zero loss in this small sample).
- HTTPS request explicitly bound to that same address returned HTTP 200. Wi-Fi was left connected; binding distinguished the LTE test from Wi-Fi connectivity.
- LTE connection is currently active. Reconnect/reboot persistence, throughput, flight coverage, and prolonged stability are not yet tested.

## Next steps

1. Determine whether the Pi has a microSD card and existing OS; preserve existing contents before any imaging.
2. Configure Pi USB modem access, APN america.bics, automatic startup/reconnect, and test LTE internet.
3. Configure a private VPN between Pi and ground station plus MAVLink routing.
4. Verify spare Lucid AIO UART pads/mapping and logic levels before wiring or changing serial parameters; retain ELRS on UART4.
5. Select and verify a 4S-compatible regulated 5 V power supply for the combined Pi/modem load. Verify power topology to avoid USB backfeeding.
6. Test telemetry, RC/GCS failsafes and reconnection with props removed, then check mounting, cooling, antennas, weight, and CG.

No aircraft parameters were changed during the laptop modem test.

## References

- [Exact Waveshare HAT documentation](https://www.waveshare.com/wiki/SIM7600G-H_4G_HAT_%28B%29)
- [Waveshare driver ZIP](https://files.waveshare.com/upload/2/24/SIMCOM_Windows_USB_Drivers_V1.0.2.zip)
- [EIOTCLUB USA dual-network V2 APN instructions](https://www.eiotclub.com/pages/usa-double-play-sim-v2-0)
- [ArduPilot Raspberry Pi MAVLink connection](https://ardupilot.org/dev/docs/raspberry-pi-via-mavlink.html)
