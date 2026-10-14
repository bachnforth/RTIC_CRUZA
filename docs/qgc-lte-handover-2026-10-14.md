# Cruza QGC over LTE: handover — 2026-10-14

## Next objective

Continue bench integration of Android QGroundControl with the TBS Lucid Wing
AIO through the Raspberry Pi Zero 2 W and SIM7600G-H HAT. The installer,
cellular connection, private network and bidirectional FC UART already work.
Next activate the phone-only MAVLink router, verify QGC telemetry and reads,
confirm video, and repeat with the Pi's Wi-Fi disconnected to prove LTE use.
The Pi was left powered. Recheck live state before acting.

Repository: https://github.com/bachnforth/RTIC_CRUZA (branch `main`).
Local checkout: `C:\Users\ebach\Documents\ChatGPT\Fixed wing Cruza`.
Detailed evidence: [audit](pi-companion-audit-2026-10-14.md),
[LTE integration](lte-integration.md), [deployment guide](../companion/README.md).

## Verified state and remaining work

| Item | Evidence / state |
|---|---|
| Pi | TFWCRUZA, user `ebach`, Zero 2 W, Raspbian 13 Trixie 32-bit; key-based SSH works |
| AIO | ArduPlane 4.7.1, system/component 1/1; latest captured heartbeats disarmed, AUTO |
| UART2 | MAVLink2, 115200, options 0; persistence verified after owner power cycle |
| UART reception | Passive eight-second capture: 665 valid frames, eight heartbeats |
| UART return path | GCS heartbeat plus read-only query: 786 valid received frames, `SERIAL2_PROTOCOL=2` reply |
| HAT | USB hub + SimTech modem detected; QMI `/dev/cdc-wdm0`, data `wwan0`, ttyUSB0–4 |
| LTE | APN `america.bics`; LTE-bound ping, DNS and HTTPS passed |
| Private network through LTE | Private SSH and phone ping passed with Pi Wi-Fi disconnected; Wi-Fi restored automatically |
| Recovery | NetworkManager recovered one controlled bearer disconnect; long outages untested |
| Camera | IMX500 detected; five-second H264 file and GStreamer RTP pipeline passed |
| Android QGC | UDP h.264 option confirmed by owner; app version and visible video still unconfirmed |
| Router / firewall | Last live check: router inactive, `/etc/cruza/firewall.nft` absent; activation pending |
| Video | Service inactive; manual stream attempted, phone picture not confirmed |
| Monitoring | `cruza-usage.timer`, `cruza-lte-health.timer`, ModemManager and tailscaled active |
| Combined acceptance | QGC over LTE, video reception, full parameter download, mission download, combined load and reconnect behavior still pending |

Captured evidence is in `logs/2026-10-14/pi-uart-received.bin`,
`pi-uart-param-reply.bin` and `pi-uart-param-reply-validation.json`.
`tools/inspect-pi-uart-capture.py` checks frame CRCs offline using pymavlink.
These files contain aircraft telemetry, including GPS positions.

## Wiring and the resolved hardware problems

| AIO connection | Pi connection (physical header numbering) |
|---|---|
| TX2 signal | Pin **10**, GPIO15 / RX |
| RX2 signal | Pin **8**, GPIO14 / TX |
| Ground | Pin **6**, GND |

Both black ground leads now connect to physical pin 6; one common ground is
sufficient. TX2/RX2 signal wires must not be grounded. Red servo power leads
are disconnected. Moving the ground from the previous underside-pad connection
to pin 6 resolved the observed zero-byte UART reception.

The modem is Waveshare **SIM7600G-H 4G HAT (B), SKU 19485**. The Pi is stacked
on the HAT; USB pogo contacts provide the modem data connection. Removing the
extra cable from the Pi micro-USB **data** port to HAT **USB1** resolved modem
detection. HAT USB1/USB2 are downstream peripheral outputs: leave that cable
removed. Do not assume the HAT uses the Pi's GPIO UART. The MAIN antenna is
connected. Pi power currently comes through its USB **PWR IN** port.

## Addresses, configuration and access

Use the existing **Headscale** control server `https://headscale.rotopter.com`.
Do not re-enroll on public Tailscale or change other nodes/server policy.

| Device | Private IP | Notes |
|---|---|---|
| Pi `tfwcruza` | `100.100.0.58` | RN08 Wi-Fi address last seen `10.229.125.15` |
| Android `invalid-ehm9ijnr` | `100.100.0.57` | Owner's phone, despite unusual name |
| Laptop `alien08` | `100.100.0.23` | Existing private network member |

PowerShell SSH (private IP, existing verified host-key identity):

```powershell
ssh -F NUL -i "$env:USERPROFILE\.ssh\id_ed25519_rpi" -o BatchMode=yes -o ConnectTimeout=8 -o HostKeyAlias=10.229.125.15 ebach@100.100.0.58
```

The local key is not in Git. Ask the owner to enter sudo credentials in an
interactive terminal when needed; do not request passwords or tokens in chat.
Only guarded shutdown is permanently password-free:
`sudo -n /usr/local/sbin/cruza-powerdown`. It refuses shutdown while the
installer/package/build processes are running. Do not execute it during testing.

Pi source: `/home/ebach/companion/`; runtime: `/opt/cruza/cruza.py`;
configuration: `/etc/cruza/config.json`. Last live configuration:

```json
{
  "serial_device": "/dev/serial0",
  "baud": 115200,
  "android_ip": "100.100.0.57",
  "mavlink_port": 14560,
  "video_port": 5600,
  "video_profile": "economy",
  "video_max_seconds": 120,
  "lte_connection": "cruza-lte",
  "lte_interface": "wwan0",
  "apn": "america.bics",
  "usage_warning_bytes": 2000000000
}
```

Installed: Tailscale 1.104.1, mavlink-router v4, rpicam-apps 1.13.0,
libcamera 0.7.2+rpt20260817, GStreamer. Package/build records and backups are
under `/var/backups/cruza/`, including `20261014T164340Z`.
`/dev/serial0` maps to ttyAMA0; GPIO serial console removed and Bluetooth
disabled by overlay. Do not reinstall or reconfigure already working components.

## Bench test sequence for the next chat

1. Read this handover and the deployment guide. Verify SSH, live config,
   `lsusb`, `mmcli -L`, `nmcli device status`, `tailscale status`, service state
   and `vcgencmd get_throttled`. Confirm AIO is powered and disarmed. Avoid
   simultaneous processes opening `/dev/serial0`. UART audit is manual only;
   stop the router before using `serial-audit.py` and restore its prior state.

2. Activate routing with the existing script, in the owner's interactive SSH
   terminal: `sudo bash /home/ebach/companion/activate-router.sh`.
   It validates configuration, installs an independent nftables table allowing
   only Android `100.100.0.57` through tailscale0 to UDP14560, then enables
   firewall/router services. It refuses replacement of an existing Cruza table;
   inspect existing rules if it refuses. Never flush the host firewall.
   Check `systemctl status cruza-firewall cruza-router`,
   `journalctl -u cruza-router -n 60 --no-pager`, listener and nftables rules.

3. On Android, keep the existing Headscale connection enabled. In QGC add a
   UDP communication link with local listening port **14550** and explicit
   server **100.100.0.58:14560**, then connect. The router's UDP server learns
   the phone endpoint when QGC sends traffic. VPN broadcast discovery is not
   assumed. Verify source 1/1 heartbeat, disarmed status, mode, battery and
   GPS/map data. Record actual QGC version and any error messages.

4. Verify a read-only parameter request and full parameter download. Compare
   UART2 values with `SERIAL2_PROTOCOL=2`, `SERIAL2_BAUD=115`, options0.
   Download the existing mission and compare its contents. Mission upload
   requires the owner to select a reviewed plan; action/arming/motion tests
   require separate explicit authorization. Do not send commands merely to
   prove connectivity.

5. Select Android QGC **UDP h.264**, receive port **5600**. With owner ready
   to observe the screen, start `sudo systemctl start cruza-video`.
   Current economy profile is 640×480, 15fps, 300kbps, with a **120-second**
   session limit. Confirm actual picture; record CPU/RAM, temperature,
   throttling, latency and interruptions. Video has no boot autostart or
   viewer detection. Reaching the deadline stops it normally; start a new
   session explicitly if needed. Inspect `journalctl -u cruza-video` on failure.

6. Prove the complete QGC path uses the HAT. Wi-Fi route metric600 currently
   wins over LTE metric700, so a working private connection alone is not proof.
   First arrange an independent, timed restoration of RN08 on the Pi. Keep
   the laptop/phone online and use private-IP SSH. For example, in a root-capable
   Pi terminal, inspect the existing profile name, then schedule:

   ```bash
   sudo systemd-run --unit=cruza-wifi-restore-qgc --on-active=90s /usr/bin/nmcli connection up netplan-wlan0-RN08
   systemctl status cruza-wifi-restore-qgc.timer --no-pager
   sudo nmcli device disconnect wlan0
   ```

   Only disconnect after confirming the restoration timer is active and the
   profile name matches the live configuration. If that unit name exists,
   inspect it and choose a fresh name. Verify wlan0 disconnected, LTE active
   and `wwan0` the sole internet default route. Confirm **Android QGC telemetry
   and a fresh parameter reply during that interval**, plus video if its basic
   test passed. Reconnect RN08 promptly or let the timer run; verify restoration.
   Record evidence that distinguishes this test from the earlier SSH-only test.

7. Test bounded recovery on the bench, with independent RC available. Verify
   telemetry resumes after a controlled link interruption, no action replay,
   stable FC state, and service recovery. Begin with Wi-Fi available as a
   recovery path. Prolonged loss, LTE cold boot and simultaneous video/telemetry
   load remain unverified. Data counter estimates are not carrier billing;
   the monthly 2GB warning currently logs only.

## Flight settings and scope

Only FC communication parameters `SERIAL2_BAUD` (57→115) and
`SERIAL2_PROTOCOL` (-1→2) were changed, with full before/after comparisons.
ELRS SERIAL4 MAVLink2/460800 and GPS SERIAL6 protocol5/115200 were preserved.
Current known safety values include `FS_GCS_ENABL=0`, `FENCE_ENABLE=0`,
`ARMING_SKIPCHK=4096`, `ARMING_MAGTHRESH=300`; low/critical battery actions1.
GCS-loss failsafe is **disabled**: do not promise LTE loss causes RTL.
Do not change failsafes, fence, arming checks, calibration or other flight
settings without owner approval. This bench integration does not establish
flight readiness or validate existing historical flight settings.

## Paste into the next chat

> Continue Cruza Android QGC integration through the LTE HAT. Read
> `docs/qgc-lte-handover-2026-10-14.md` in the RTIC_CRUZA checkout first.
> UART is now bidirectional after grounding to Pi physical pin 6; LTE and
> Headscale already work. Inspect live state, activate the existing phone-only
> router, guide my Android UDP link/video setup, and verify telemetry and a
> read-only parameter reply with Pi Wi-Fi disconnected and timed restoration.
> Preserve ELRS/GPS and all flight safety settings. Do not arm, run motors,
> change modes or upload a mission without my separate instruction. Keep
> useful evidence and documentation in Git; never store credentials.
