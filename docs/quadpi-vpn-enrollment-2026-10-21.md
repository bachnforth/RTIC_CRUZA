# QuadPi VPN enrollment — October 21, 2026

QuadPi is enrolled and online on the same Headscale VPN as TFWDRONE.

| Item | Verified value |
|---|---|
| Control server | `https://headscale.rotopter.com` |
| Node name | `quadpi` |
| VPN IPv4 | `100.100.0.10` |
| VPN IPv6 | `fd7a:115c:a1e0::a` |
| Policy tag | `tag:team1` |
| Backend | `Running`, online |
| Mesh address | `10.223.79.20/16` on `eth0` |
| Partner node | `tfwdrone`, `100.100.0.6`, `tag:team1` |

## Installation and enrollment

Installed Tailscale 1.104.2 arm64 from QuadPi's existing official signed Debian
trixie repository. Five new packages were installed; existing packages were not
upgraded. `tailscaled.service` is enabled and active for automatic startup.

Enrollment used an owner-supplied Headscale preauthentication key with these
settings; the credential is intentionally omitted:

```bash
sudo tailscale up \
  --login-server=https://headscale.rotopter.com \
  --hostname=quadpi \
  --accept-routes=false \
  --accept-dns=false \
  --auth-key=file:/dev/stdin \
  --timeout=25s
```

The key was supplied through standard input. Subnet-route acceptance and VPN DNS
remain disabled to preserve local mesh routing and existing DNS. The initial
interactive enrollment could not be completed through the owner's Headplane
session because `ebach` has the Auditor role and Add Device is disabled. Key-based
enrollment subsequently succeeded without changing server roles or policy.

## Verification

- QuadPi returned its assigned VPN addresses, `Running` backend, online status,
  and `tag:team1` from `tailscale status --json`.
- Encrypted VPN ping from QuadPi to laptop `alien08` (`100.100.0.23`) succeeded.
- Ordinary SSH from the laptop to `100.100.0.10` authenticated with the existing
  key and strict host verification against QuadPi's known mesh host identity.
- Mesh SSH remained available. QuadPi's route to laptop `10.223.58.11` still
  selected `eth0` with source `10.223.79.20`.
- `tailscaled`, `safety-mavlink-filter`, `mesh-logger`, and `cruza-path-health`
  were active after enrollment.

Laptop Wi-Fi 2 was reconnected using its existing Meshnet-1620 profile to RN08
Handheld; Carp was unavailable. QuadPi's internet connection at verification was
`wlan0`, address `10.237.44.177/24`, default gateway `10.237.44.157`.

## Remaining checks

TFWDRONE was visible as a VPN peer but offline, so connectivity between the two
quads remains untested. Boot startup is configured but has not been tested with
a reboot during this work.

`picam-stream` was already in an auto-restart loop before installation
(`NRestarts=31` at inspection). It was not modified or investigated here.
