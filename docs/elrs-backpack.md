# RadioMaster Pocket ELRS TX backpack

## Fixed-SSID firmware

The Pocket's internal TX backpack now runs a custom ExpressLRS Backpack 1.5.9
image with a fixed UID. This prevents the six-character suffix in its access
point name from changing between restarts.

- Target: `radiomaster.txbp.pocket` / `ESP_TX_Backpack`
- Upstream: ExpressLRS Backpack tag `1.5.9`, commit
  `437a4f43e02a448ab66ec6520ec55cee4fcb10a6`
- Stable access point: `ExpressLRS TX Backpack 456B22`
- Wi-Fi password: `expresslrs`
- Backpack address in AP mode: `10.0.0.1`
- Laptop address assigned during verification: `10.0.0.100`

Recovery images are stored in `firmware/`:

| File | Purpose | SHA-256 |
|---|---|---|
| `pocket-backpack-1.5.9-fixed-uid.bin.gz` | Upload from the backpack's Wi-Fi updater | `3CFFFA1A2718E794B84507C050B390B2656915FF6B3B644ADBFD9C7958D21D17` |
| `pocket-backpack-1.5.9-fixed-uid.bin` | Uncompressed recovery image | `DFF1A19DEFB3C0BE6E74CADB0007630EAF60194856DFF4DEFBC62DAF4BE5CC62` |

The image was built from the upstream 1.5.9 source, then configured with the
project's ELRS binding phrase using Backpack's `python/binary_configurator.py`
for target `radiomaster.txbp.pocket`. Keep the project binding phrase private
when sharing these notes or firmware outside the project.

## Normal operation

1. In the Pocket's ExpressLRS Lua script, set `Link Mode = MAVLink` while the
   receiver is not connected.
2. Set `Backpack > Telemetry = WiFi`.
3. Join `ExpressLRS TX Backpack 456B22` on the laptop's `Wi-Fi 2` adapter, or
   run `tools/connect-backpack.ps1`.
4. In QGroundControl, use a UDP link with local port `14550` and server
   `10.0.0.1:14555`.

Do not use the separate **Enable Backpack WiFi** command for normal MAVLink
operation. That starts firmware-update mode; its plain `ExpressLRS TX
Backpack` SSID is not the MAVLink access point.

## What the status fields mean

- `http://10.0.0.1/mavlink` reports `enabled:true` only when the backpack is
  running its MAVLink Wi-Fi service.
- The backpack learns the GCS IP from any UDP datagram received on port
  `14555`; it does not require a particular MAVLink message or source port.
- Until the first datagram arrives, `gcs` can legitimately show `IP UNSET`.
- Aircraft telemetry is sent to the learned GCS IP on UDP port `14550`.

## Verified 2026-10-08

A full Pocket power cycle produced the same SSID, Windows reconnected
automatically, firmware 1.5.9 reported `enabled:true`, and a test UDP datagram
changed `gcs` from `IP UNSET` to `10.0.0.100` while incrementing
`packets_up`.
