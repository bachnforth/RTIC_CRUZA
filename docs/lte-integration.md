# LTE integration — 2026-10-13

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
