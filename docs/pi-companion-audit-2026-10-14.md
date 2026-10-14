# Pi companion audit — 2026-10-14

## Evidence and confirmed configuration

SSH key login succeeds as the owner account on 10.229.125.15, hostname TFWCRUZA,
MAC 88:A2:9E:61:06:E0. SSH initially refused connections after imaging; a bootfs
`ssh` marker was added, and the laptop public key was subsequently installed by
the owner. Existing Imager account and Wi-Fi configuration were preserved.

- Live model: Raspberry Pi Zero 2 W Rev 1.0.
- Live OS: Raspbian GNU/Linux 13 (Trixie), armv7l, kernel 6.18.50+rpt-rpi-v7.
- Live RAM: 424 MiB reported; approximately 306 MiB available after camera test.
- Root storage: 29 GiB filesystem, approximately 26 GiB free.
- RN08 Wi-Fi works; NetworkManager and SSH active.
- Time zone is America/New_York; America/Chicago is recommended but not changed.
- rpicam-apps v1.13.0; libcamera v0.7.2+rpt20260817. IMX500 detected at camera 0.
- Five-second H264 recording at 640x480, 15 FPS, 400 kbps requested succeeded;
  `/home/ebach/cruza-camera-test.h264` is approximately 72 KiB. This verifies
  capture/encoding only, not live video reception or prolonged performance.
- `vcgencmd get_throttled` returned 0x0; initial temperature 44 C. These are
  short bench observations, not a combined Pi/modem power-load test.
- USB enumeration contains only the root hub. Despite owner-confirmed HAT
  attachment, SIM7600 and HAT hub have not enumerated. Check power/data topology.
- GPIO serial device was absent, and `console=serial0,115200` remains in the
  kernel command line. GPIO MAVLink requires UART enable and console removal.
- NetworkManager exists; ModemManager, GStreamer, Tailscale and mavlink-router
  were absent in the initial audit. Package installer prepared, not yet run.
- No existing companion networking/video services found.

The repo establishes ArduPlane 4.7.1 on TBS_LUCID_H7_WING_AIO, functioning ELRS
RC/telemetry and AUTO flights. This is historical flight-controller evidence,
not a fresh live FC readback. October 13 snapshot: SERIAL4 MAVLink2/460800 for
ELRS; SERIAL6 GPS/115200; SERIAL2 disabled/57600; SERIAL3 MSP DisplayPort.
UART2 TX/RX are on signal positions 7/8 after S1..S6 of the servo connector.
Pi GPIO14/TX (physical 8) goes to AIO RX2, GPIO15/RX (physical 10) to TX2,
and a shared ground is required. No AIO power-row wire goes to Pi GPIO.

Earlier laptop LTE test verified SIM7600G-H (B), USB VID 1e0e/PID 9001,
EIOTCLUB dual-network SIM, APN america.bics, T-Mobile BICS registration and
LTE-bound ping/HTTPS connectivity. That does not verify Pi modem mode, Linux
drivers, recovery, CGNAT or current SIM allowance.

## Recommended architecture

NetworkManager/ModemManager own LTE sessions; Tailscale provides authenticated
outbound private connectivity through carrier NAT; mavlink-router v4 carries
unchanged MAVLink; rpicam hardware H264 output is packetized by GStreamer as
RTP/H264 to the Android tailnet IP. No general-purpose AI processing, transcoding,
web dashboard or container. The IMX500 supplies camera frames, not H264 encoding.

Tailscale is already installed on the laptop, reducing setup work. Android and
Pi must join the intended tailnet; restrict grants to the Android device and
Pi's MAVLink UDP port. Direct connections are preferable; relayed throughput
and latency must be measured. VPN is an overlay over LTE/Wi-Fi, not another
independent physical radio link. A WireGuard VPS adds provisioning and ongoing
maintenance; use only if direct/relayed Tailscale performance fails validation.

Physical modem USB mode must be inspected before choosing QMI/MBIM/ECM/PPP.
The implementation intentionally does not send USB-mode-switch AT commands.
The HAT requires a powered USB data path to the Pi USB/OTG port; PWR IN has
no USB data. Check the exact HAT's USB routing and supply jumpers before
connecting multiple power sources. No GPIO header power assumptions were made.

## Safety observations and unresolved dependencies

Latest retained FC snapshot has FS_GCS_ENABL=0, FS_LONG_ACTN=1,
FS_LONG_TIMEOUT=5, FS_SHORT_ACTN=0, BATT_FS_LOW_ACT=1,
BATT_FS_CRT_ACT=1, FENCE_ENABLE=0, ARMING_SKIPCHK=4096,
ARMING_MAGTHRESH=300. These are existing values; none changed. GCS-loss
failsafe is disabled in that snapshot: do not claim LTE loss automatically
causes RTL. RC-loss timing, mission continuation, GPS loss and reboot outcomes
require current configuration review and bench/controlled flight validation.
Any proposed safety-parameter changes require the owner's explicit approval.

Remaining: sudo installation, modem enumeration and power topology, active
UART and fresh FC snapshot, tailnet enrollment and Android IP/QGC version,
Android RTP video confirmation, simultaneous-load benchmark, LTE-bound internet
test, outage/reconnection test and all aircraft command/flight checks.

## Implementation and software checks

`companion/` contains the Python supervisor/diagnostic utility, root installer,
separate UART/LTE/router activation scripts, example configuration and systemd
units. Staged at `/home/ebach/companion` on the Pi. Router/video are not enabled.
Three Python tests passed on the actual Pi: endpoint restrictions, private
router configuration and data-counter resets/day boundaries. Python compilation,
shell syntax checks and systemd unit verification completed without diagnostics.
The signed Tailscale Trixie repository URL returned HTTP 200.

The camera output is 73,728 bytes and contains H264 SPS, PPS, IDR and non-IDR
NAL units. This is additional structural evidence of a successful encoded
recording; decoded image quality and Android playback remain unverified.

`sudo -n true` reports a password required. The owner has been given an SSH
terminal command to run the installer with a private sudo password prompt.
No system packages, services, GPIO boot settings or FC settings have been
changed by the agent during this audit; only staged home-directory files and
the camera test recording have been added on the Pi.

## Installation continuation and shutdown permission

The first owner-started dependency download was interrupted by the requested
shutdown; subsequent checks found an empty package audit and no package-install
logs. A later restart ended when the Pi rebooted; no agent reboot was issued.
Cause of that reboot is unconfirmed. The owner switched to USB power and
restarted the installer as transient systemd unit `cruza-install`.

Password-free shutdown permission was installed and checked with
`sudo -n -l /usr/local/sbin/cruza-powerdown`. The installed helper is root-owned,
mode 755; sudoers permits only that no-argument command. Running its guard as
the unprivileged owner while the installer was active correctly refused
shutdown. No shutdown was issued in that test. The main installer now has an
exclusive lock preventing simultaneous runs. Package download/installation
completion and remaining services must still be verified.

## Installation verified — continuation on 2026-10-14

Dependency download failed once on libllvm19 with a hash mismatch following an
IPv6 timeout. Downloaded the same version over IPv4 and HTTPS, verified SHA256
`50f3ef5c7b5dc408147d82632221aac2687c0146911ba5509add8e2e529ad045`
against APT's signed metadata, placed it under APT's expected cache filename,
and resumed using existing cached packages. Package integrity checks were not
disabled. Installer now uses IPv4 and three retries. Successful completion
recorded at 16:51:55 UTC; backup `/var/backups/cruza/20261014T164340Z`.

- mavlink-router v4 built and installed; Tailscale 1.104.1 installed.
- ModemManager, tailscaled, usage timer and LTE health timer active.
- Package audit empty and systemd unit verification produced no diagnostics.
- Local GStreamer H264 parse/RTP packetization to fakesink exited successfully;
  UDP sink DSCP property is available. Android video delivery remains unverified.
- Upstream Meson build reported no tests defined; this is not a passing upstream
  test suite. Three project Python tests previously passed on the Pi.
- Password-free no-argument shutdown permission installed and sudoers validated.
- GPIO console removed; UART enabled with disable-bt overlay. Backups are under
  `/var/backups/cruza/uart-20261014T165424Z`. hciuart.service does not exist on
  this image; absence was recorded rather than assumed to have been disabled.
- Time zone changed to America/Chicago.
- Reboot issued only after confirming installer/apt/dpkg/Ninja were inactive.
  After reboot `/dev/serial0 -> ttyAMA0` exists with dialout permissions, camera
  remains detected, all four monitoring/network services restart and throttling
  flags remain 0x0. Router and video intentionally remain inactive.
- Tailscale enrollment initiated and sign-in page queued in Codex. After reboot
  the Pi still reports logged out: VPN connection is not verified.
- USB still lists only root hub; ModemManager reports no modems.

Remaining blockers: LTE HAT power/data topology and enumeration; Tailscale
sign-in and Android endpoint/version; live AIO UART2 settings/heartbeat; Android
video, mission/command tests and combined-load/outage tests. No flight-controller
parameters, arming state or motor outputs have been changed during this work.

## Existing Headscale network identified

Owner supplied Headplane screenshot at headscale.rotopter.com. Read-only laptop
`tailscale debug prefs` confirms ControlURL=https://headscale.rotopter.com.
The Pi was initially directed to the public Tailscale login server; corrected
with `tailscale up --login-server=https://headscale.rotopter.com --hostname=tfwcruza`.
It generated a Headscale registration URL, queued for owner approval. Node
enrollment, private IP assignment and reachability remain unverified until that
approval completes. No existing Headscale nodes or policy have been changed.

Subsequent live status confirms enrollment as tfwcruza under ebach, private
IPv4 100.100.0.58, on the intended Headscale server. Android peer 100.100.0.57
is listed offline; do not assume this is the intended active ground station
without owner confirmation.

## Android endpoint and short video test

Owner confirmed Android node invalid-ehm9ijnr, IP 100.100.0.57, through a
Tailscale screenshot and confirmed UDP h.264 is available in Android QGC.
Pi-to-phone probes initially used DERP(mia), 191–275 ms; later live status
showed a direct connection. Updated only android_ip in config with a backup
at `/var/backups/cruza/peer-20261014T174804Z`.

Eight-second passive UART observation at 115200 received zero bytes, transmitted
zero bytes and restored original termios settings. It does not validate a
MAVLink heartbeat or prove a wiring fault; AIO power/protocol remain unknown.

Started a manually requested 120-second economy video test: 640x480, 15 FPS,
300 kbps requested. Camera/RTP processes run successfully. Short sample:
rpicam about 12% CPU / 16.5 MiB RSS; GStreamer about 1.3% / 11.5 MiB RSS;
251 MiB system memory available; 53.2 C; throttling flags 0x0. This is a
Wi-Fi/private-network test, not simultaneous LTE/MAVLink validation. Android
picture confirmation remains pending. Video stays disabled at boot and stops
at the configured two-minute limit. No flight commands were sent.

Owner confirms the AIO is unpowered, explaining the lack of received serial
traffic. The 120-second video test ended normally with `failed=false` and
systemd success. Subsequent phone probe returned via relay at 860 ms, so direct
connectivity is intermittent in this bench topology. Android decoding/picture
still requires owner confirmation; no reception pass is claimed.

## Live flight-controller UART configuration — 2026-10-14

Owner connected AIO USB and closed QGC to release COM17. Read disarmed fixed-wing
ArduPilot heartbeat from system/component 1/1 and AUTOPILOT_VERSION 4.7.1.
Collected complete 1245-parameter snapshots before and after changes. UART2
initially SERIAL2_PROTOCOL=-1, BAUD=57, OPTIONS=0. Applied only BAUD=115 and
PROTOCOL=2; independent readbacks match, OPTIONS remains 0. Full comparison
found no unrelated changes, including ELRS/GPS and safety parameters.

Evidence: `params/cruza_params_2026-10-14_181011Z_before_pi_uart.params`,
`params/cruza_params_2026-10-14_181011Z_after_pi_uart.params`, and
`logs/2026-10-14/pi-uart-2026-10-14_181011Z/verification.json`.
Utility `tools/configure-pi-uart.py` audits by default and writes only those
UART2 communication parameters with --apply. No reboot, arming or motor commands
were sent. UART reception after AIO restart remains pending.

After owner-reported AIO restart, complete USB snapshot
`params/cruza_params_2026-10-14_181442Z_before_pi_uart.params` contains 1256
parameters and confirms SERIAL2_PROTOCOL=2, BAUD=115, OPTIONS=0 persisted.
Controller is disarmed. Additional serial-port stream parameters appearing
after protocol activation are expected. Passive Pi UART test still receives
zero bytes. Physical wiring/ground and possible HAT UART conflicts require
inspection before additional parameter changes.

## HAT USB detection resolved

Owner identified a cable from the Pi data port to HAT downstream USB1, in
addition to the stacked pogo connection. Manufacturer describes USB1/USB2 as
extended peripheral ports, with pogo/MicroUSB as hub input. After owner removed
that cable and rebooted, USB enumeration shows Terminus hub 1a40:0101 and modem
1e0e:9001. Drivers option and qmi_wwan attached; ttyUSB0–4 and cdc-wdm0 exist.
ModemManager detects SIMCOM_SIM7600G-H, firmware LE20B04SIM7600G22, registered
on LTE roaming AT&T (310410), packet service attached, signal quality 67.
PIN2 status is reported, but modem registration succeeds; no PIN changes made.
No bearer/data session yet; wwan0 down and NetworkManager GSM disconnected.
This resolves USB enumeration, not internet connectivity. Root configuration
requires the owner's sudo password after this reboot.

The exact B HAT uses USB pogo data; no shared Pi GPIO UART connection was
established from stacking alone. Earlier generic HAT UART-conflict suggestions
must not be treated as a diagnosed cause. AIO UART still has zero received
bytes and remains a separate wiring/data-path investigation.

## LTE data, NAT traversal and recovery verified

Owner ran configure-lte.sh --create, activating cruza-lte/APN america.bics and
configuring usage interface wwan0. Three LTE-bound pings passed; LTE-bound HTTPS
returned 200; interface-bound DNS to 8.8.8.8 passed. LTE IP 100.80.66.223 lies
within CGNAT shared-address space. Temporarily disconnected only Pi Wi-Fi,
with an independently scheduled restore timer. Private SSH to 100.100.0.58
and Pi-to-phone reachability succeeded with wwan0 as the sole default route.
RN08 restored automatically; neither Pi nor FC rebooted for the network test.

Brief modem-bearer disconnect was followed by automatic NetworkManager
reactivation; recovered LTE-bound HTTPS returned 200. Autoconnect yes and
unlimited retries confirmed. Longer radio/coverage outages remain untested.
Live usage samples persist and no throttling flags appeared. Details and
small-sample timing limitations are in docs/lte-integration.md.

## References

- [AI Camera support](https://www.raspberrypi.com/documentation/accessories/ai-camera.html)
- [Exact LTE HAT](https://www.waveshare.com/wiki/SIM7600G-H_4G_HAT_%28B%29)
- [Retained LTE evidence](lte-integration.md)
- [MAVLink router configuration](https://github.com/mavlink-router/mavlink-router/blob/v4/examples/config.sample)
- [QGC video settings](https://docs.qgroundcontrol.com/master/en/qgc-user-guide/settings_view/video.html)
- [Tailscale connection types](https://tailscale.com/docs/reference/connection-types)
