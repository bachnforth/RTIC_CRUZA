# Mesh radio roles and RN20 validation — 2026-10-19

## Current role assignment

The owner selected the following deployment plan on October 19, 2026. These
assignments supersede earlier RN08-as-GCS and RN03-as-quadpi bench arrangements.

| Radio | Mesh MAC | Management IPv4 | Assigned role |
|---|---|---|---|
| RN20 | 00:30:1A:3C:C4:6E | 10.223.196.110/16 | GCS radio; USB data connection to the laptop |
| RN08 | 00:30:1A:3C:C4:82 | 10.223.196.130/16 | Radio with quadpi |
| RN03 | 00:30:1A:3C:C4:62 | 10.223.196.103/16 | Replace the Doodle Mini in its intended aircraft role |

quadpi retains its recorded address, 10.223.79.20/16. The planned topology is:

```text
GCS laptop -- USB data -- RN20 -- 907 MHz mesh -- RN08 -- quadpi
                              |
                              +-- 907 MHz mesh -- RN03 -- Mini replacement role
```

The new physical RN08-to-quadpi attachment and RN03 aircraft installation were
not independently verified after this role decision. RN20's successful mesh
tests below preceded that deployment plan. This update records the plan and
bench results; it does not claim a completed aircraft installation.

## Verified RN20 mesh setup

- RN20 is the wearable labeled RM-1700-22W3, MAC 00301A3CC46E.
- Mesh ID 666; channel 20 / 907 MHz; bandwidth 10 MHz; Mesh Point mode.
- Effective wireless encryption is WPA3-SAE (CCMP), with the mesh key matching
  RN03's effective wireless key. No password is recorded here.
- The selected expected device count is 3 to 5.
- The laptop USB adapter was Ethernet 3, LAN9500A, MAC 00-30-1A-3C-C4-71,
  using 10.223.58.10/16 and fallback management address 192.168.153.10/24.
- RN20's fallback management page is 192.168.153.1. Use unique 10.223.x.x
  management addresses to distinguish radios on the mesh.

The final RN20 wireless screenshot showed live links to both existing peers:

| Peer | RX link rate | TX link rate | Width |
|---|---|---|---|
| RN08, MAC ending C4:82 | 19.5 Mbit/s | 19.5 Mbit/s | 10 MHz |
| RN03, MAC ending C4:62 | 9.8 Mbit/s | 9.8 Mbit/s | 10 MHz |

Fresh laptop checks reached RN08 in 16 ms and quadpi in 5 ms; TCP port 22
responded on both. Windows route readback selected Ethernet 3 with source
10.223.58.10 for these destinations. The spare Wi-Fi adapter was separately
connected directly to RN03 during troubleshooting, so RN03 reachability alone
was not used as proof of the RN20 mesh path. These are short bench checks,
not application throughput, range, or sustained reliability measurements.

## Configuration issue resolved

RN20 initially listed both peers but received no mesh data. Its Simple
Configuration password field matched RN03, while the actual wireless mesh key
in `etc/config/wireless`, section `wifi0`, differed. Comparing the downloaded
configuration archives identified this discrepancy. The Wireless Security panel
also initially showed WPA2-PSK on RN20 versus WPA3-SAE on RN03.

The owner set RN20's mesh interface to WPA3-SAE and copied the matching key
directly into Network Configuration -> Wireless -> Edit mesh 666 -> Wireless
Security, then used Save followed by Save & Apply. Subsequent traffic checks
and bidirectional peer link rates confirmed RN20 joined the working mesh.
For future additions, compare the effective wireless configuration; matching
Simple Configuration fields alone is insufficient. Keep each radio's unique
IP/MAC identity when using another radio as a configuration reference.

The configuration archives contain credentials and remain local in Downloads.
They are excluded from this documentation commit. Radio clocks showed 2022;
archive filenames reflect those incorrect clocks, not the test date.

## Laptop routing and remaining deployment work

Tailscale supplied an overlapping 10.223.0.0/16 route during troubleshooting.
Administrator-approved temporary ActiveStore host routes were installed for
the two remote radios. RN03's /32 route was subsequently moved to Wi-Fi 2 for
direct configuration access, using temporary address 10.223.58.11/16. RN08's
/32 route remained on Ethernet 3. Temporary routes disappear on reboot; current
interface names and route selection must be checked when reconnecting equipment.
The existing `dashboard/fix-mesh-routes.ps1` targets the older Alfa Wi-Fi GCS
arrangement and should not be run blindly for the RN20 USB GCS deployment.

Before accepting the final deployment, connect RN08 to quadpi and RN03 in the
Mini's intended role, remove the temporary direct RN03 Wi-Fi diagnostic path,
and verify laptop-to-endpoint traffic through RN20 again. No flight-controller,
MAVLink, camera destination, or Tailscale enrollment changes were made for this
role update. Cruza's existing RC and LTE/GCS operation remains independent of
the optional mesh path.
