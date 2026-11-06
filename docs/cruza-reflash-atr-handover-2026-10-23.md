# Cruza reflash + ATR observation deployment — handover (2026-10-23)

Session covered two things: (1) building the Cruza **observation / areas-of-interest**
feature in this repo, and (2) **reflashing the Cruza Pi** and standing the whole
stack back up on it. Everything below is the state at end of session.

## Scope / safety boundary (read first)
This is **operator-in-the-loop ISR cueing**, not autonomous targeting. The Cruza
flags areas of interest; a human validates each on the dashboard; a human decides
any tasking. There is **no MAVLink sender anywhere** and nothing auto-tasks or
auto-engages. The detector is camera-only (no FC/MAVLink/route/modem access). If
asked to make detection auto-task or put target recognition on the TFW **dropper**
platform, that's the line — don't.

## What the feature is
Cruza IMX500 runs on-sensor object detection (stock MobileNet-SSD COCO) → publishes
advisory JSON (class, score, angles off boresight) to loopback UDP 15620 →
`observe-tap.py` frames it over SSH → dashboard `Observe` reader → `ObservationStore`
→ `/status` → `dist/observations.js` joins angles with Cruza telemetry to estimate
bearing/ground point → **Areas of interest** panel → operator Confirm/Dismiss →
"Send to dispatch" drops a candidate into the existing preview-only command panel.

Committed to this repo (branch `cruza-quad-link-test`, commit `7ac3ffc`, **not pushed**):
`companion/observe.py`, `observe-tap.py`, `systemd/cruza-observe.service`,
`deploy-observe.sh`, `config.example.json` (observe block); `dashboard/observations.py`,
`test_observations.py`, `dist/observations.js`, and edits to `server.py`,
`dist/{fleet-map,fleet,index.html,fleet.css}`. 40 dashboard tests pass.

## The Cruza Pi (reflashed this session)
- **Hardware:** Raspberry Pi Zero 2 W + Sony **IMX500** AI camera + **SIM7600G-H** LTE.
- **OS:** 64-bit Raspberry Pi OS (Debian 13 trixie, `ID=debian`, `aarch64`).
- **User:** `jbrascom` (NOT ebach). Passwordless sudo.
- **Hostname:** TFWCRUZA. **Tailnet:** `100.100.0.34` (node `tfwcruza1`, tagged into
  the devices group by ebach). **RN03 (bench WiFi):** `10.65.247.9`.
- **Access:** `ssh jbrascom@100.100.0.34` (tailnet) or `10.65.247.9` (RN03) with
  `~/.ssh/id_ed25519_pi` (the `windows-claude-to-pi` key). Host key is in known_hosts.

### What is installed / running
- Companion base installed (`/opt/cruza/cruza.py`, `/etc/cruza/config.json`,
  mavlink-router built at `/usr/local/bin/mavlink-routerd`, all cruza-* units,
  ModemManager + tailscaled + usage/lte-health timers active).
- **IMX500 detector LIVE** (`cruza-observe.service` enabled+active). Verified by a
  live capture: it detected a person on the bench (scores 0.56–0.68, az/el tracked
  movement). Watches person/car/truck/bus/boat/bicycle/motorcycle/airplane.
- **LTE up and failover PROVEN**: SIM7600 registered on AT&T (roaming, 71% signal,
  APN `america.bics`). With WiFi off, the tailnet held over LTE — `tailscale ping`
  to the ground laptop 6/6 at ~150–215 ms. Routes: WiFi metric **600** (bench) /
  LTE metric **700** (flight) → automatic failover when WiFi range is lost.
- Dashboard (`RTIC_CRUZA/dashboard/server.py`) now points cruza at `100.100.0.34`,
  user `jbrascom`, key `id_ed25519_pi`. SSH path to the observe tap verified.

## Gotchas learned (don't re-hit these)
- **Recent Raspberry Pi OS uses cloud-init** (`user-data`/`network-config` on the
  boot partition) — same layout as Ubuntu. Don't mistake it for Ubuntu; check
  `issue.txt` (pi-gen = Raspberry Pi OS).
- **Imager stored the SSH key without its `ssh-ed25519` prefix** once (invalid key)
  and had `ssh_pwauth` off → would have locked us out. Verify the key line in
  `user-data` is a full `ssh-ed25519 AAAA… comment` line.
- **`install.sh` was gated to 32-bit Raspbian.** Adapted its OS guard to accept
  64-bit `debian` and made the Tailscale repo use `$ID` (committed locally, unpushed).
- **`ebach` hardcoding.** `install-powerdown.sh`, `deploy-observe.sh`, and the
  `User=` in `cruza-video.service`/`cruza-observe.service` assume user `ebach`;
  that broke the install (`id: 'ebach': no such user`) and the detector service
  (`217/USER`). Fixed to `jbrascom` **on the Pi only** — the repo still hardcodes
  `ebach`. Proper fix: parameterize the owner user.
- **ModemManager only saw the SIM7600 after a clean reboot** (boot-timing race);
  QMI libs were fine. If `mmcli -L` says "No modems," reboot before deeper debugging.
- **RF safety:** never bring the LTE connection up (transmit) with the antenna off.
- **Tailscale enrollment churn:** killing `tailscale up` abandons the pending key,
  and restarting tailscaled (install does) cycles it. A pre-auth key avoids the
  whole dance. The node connected only once the login persisted and ebach approved
  the *current* key, then tagged the node into the devices group.
- **Old stale node:** `tfwcruza` / `100.100.0.58` (offline) still holds the clean
  name — ask ebach to delete it in Headscale.
- Phone-hotspot SSH drops on long sessions; run long work as detached
  systemd/nohup units and read result files, not one long SSH.

## Done vs. left
Done: reflash+provision, camera+IMX500 firmware, detector live, Tailscale + LTE
failover, companion base, dashboard pointed at the new IP.

Left:
1. **Launch the dashboard** (`RTIC_CRUZA/dashboard`) and confirm AOI cues render
   with a person/vehicle in frame. (Video feed needs `/opt/cruza-video-tap.py`,
   not yet deployed — run `dashboard/deploy-cruza.sh`-equivalent; AOIs + telemetry
   don't need it.)
2. **QGC side:** `sudo bash ~/companion/configure-uart.sh` + reboot (FC MAVLink
   path), set `android_ip` in `/etc/cruza/config.json`, `activate-router.sh`,
   enable `cruza-router`/`cruza-video`.
3. **Calibrate** camera FOV (`hfov_deg`/`vfov_deg` in Pi config) and mount angles
   (`MOUNT_YAW_DEG`/`MOUNT_PITCH_DOWN_DEG` in `dist/observations.js`) — bearings are
   estimates until measured on the airframe.
4. **Repo cleanup:** parameterize the `ebach` owner user; commit/push the install.sh
   64-bit fix + the dashboard new-IP/user/key changes when ready.
5. Ask ebach to delete the stale `tfwcruza`/`100.100.0.58` node.

## QGC-side update (end of session 2026-10-23)

- **Dashboard launched and verified LIVE.** Ran `python server.py` in
  `RTIC_CRUZA/dashboard` (needs `runtime/mediamtx-*/mediamtx.exe`, present). It
  served `http://127.0.0.1:8765` and the **Areas of interest panel showed real
  cues** from the Cruza over the tailnet (Car, Person). Confirm/Dismiss work.
  Bearings read "unavailable" because Cruza telemetry isn't reaching the dashboard
  yet (needs the router + an active QGC peer, below).
- **UART / FC path: DONE.** `sudo bash ~/companion/configure-uart.sh` ran + reboot.
  `/dev/serial0` → `/dev/ttyAMA0`. The FC is sending **valid MAVLink2** at
  **115200** (sysid 1 / compid 1 ArduPlane, ATTITUDE frames seen), so the
  autopilot's SERIAL2 settings survived the reflash and the UART is wired right.
  NOTE: `xxd` is NOT installed on the Pi — analyze serial with Python/`od`, not xxd.
- **Two QGC phones to allow:** jbrascom's phone **`100.100.0.60`**
  (`invalid-futd3sjj`), partner/ebach's phone **`100.100.0.57`** (`rn08-g24`).
- **`activate-router.sh` was edited (local repo, unpushed)** to accept MULTIPLE
  phones: it now reads `android_ip` plus optional `android_ip2` (str or list) and
  emits an nft `accept` line per peer. mavlink-router's UDP server already serves
  all firewall-permitted peers, so no router change is needed for dual-GCS
  telemetry. This edit is NOT yet on the Pi.

### Router: DONE (dual-phone QGC telemetry)
- `activate-router.sh` deployed to the Pi (dual-peer version), `android_ip` =
  `100.100.0.60` + `android_ip2` = `100.100.0.57` set in `/etc/cruza/config.json`,
  config validates `endpoint_ready: true`.
- `cruza-firewall` + `cruza-router` are **enabled + active**. Firewall accepts UDP
  14560 on `tailscale0` from BOTH phones, drops the rest. `mavlink-routerd` is
  listening on `100.100.0.34:14560` and reading the FC cleanly (`CRC error 0%`).
- **On each phone:** QGC → UDP link to `100.100.0.34:14560` → telemetry over LTE.
- To change peers later: edit `android_ip`/`android_ip2`, then
  `sudo nft delete table inet cruza` and re-run `activate-router.sh` (it refuses
  to replace an existing table otherwise).

Still remaining:
5. **Video to both phones — BLOCKED on an IMX500 architecture limit (important).**
   The `multiudpsink` fan-out change IS done in `cruza.py` `video()` (sends one
   RTP stream to `android_ip` + `android_ip2` + optional loopback mirror), deployed
   to `/opt/cruza/cruza.py`. BUT starting `cruza-video` fails: plain `rpicam-vid`
   gets "Camera frontend has timed out" because **the IMX500 needs its NN firmware
   loaded to stream at all** — `picamera2`/the detector loads it, `rpicam-vid` does
   not. AND it's one camera: `cruza-video` (rpicam-vid) and `cruza-observe`
   (picamera2) cannot both own it. So `cruza-video` was **disabled** again; the
   detector is the camera owner. The right fix is to **merge video + detection into
   one picamera2 process**: the IMX500 yields encodable frames AND inference
   metadata in the same capture, so one service can H264-stream to both phones
   (via the gst multiudpsink `clients=` list already built) and emit detection
   records to the loopback. That replaces the separate `cruza-video` + `cruza-observe`
   services. Not a config tweak — a real change. (A video-ONLY fallback is possible
   by adding `--post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json`
   to the rpicam-vid args so it loads firmware, but that still can't run alongside
   the detector.)

   **Merge built + attempted — blocked on a camera-pipeline bug; needs on-Pi
   debugging.** `companion/stream.py` + `systemd/cruza-stream.service` (deployed to
   `/opt/cruza/stream.py` and `/etc/systemd/system/`) are the one-process service:
   picamera2 loads the IMX500, H264-encodes and pipes to a gstreamer `multiudpsink`
   fan-out (both phones + optional mirror), while the same loop reads
   `imx500.get_outputs` and publishes detections to loopback 15620. It **starts**
   (emits `stream_start` with both phone dests) but the camera **frontend times
   out** and no RTP flows — with both video AND preview configs. The detector
   (picamera2, no encoder) works, so the trigger is adding the H264
   encoder/`start_recording`. Leading hypothesis: the `FileOutput → gst.stdin` pipe
   isn't consumed fast enough, so the encoder output blocks and starves the camera
   frontend. Debug on the Pi (not over the hotspot): test the gst pipeline
   standalone (videotestsrc/file); try picamera2's own RTP output instead of piping
   to gst, or a non-blocking writer; encode from a lores stream; lower
   FrameRate/bitrate. `cruza-stream` is now **disabled**; working config is
   `cruza-observe` (detector) re-enabled. Remote iteration is impractical — the
   hotspot drops on nearly every multi-step SSH; do this with the Pi on a stable
   network or local console.
6. **Dashboard bearings:** once the router is up and a phone's QGC is connected,
   the Cruza's outgoing MAVLink on `tailscale0:14560` is what the dashboard's
   telemetry observer watches — that's what fills in bearings/map positions on
   the AOI cues. The telemetry-observer service from the Oct-15 dashboard update
   was NOT reinstalled by `install.sh`; if telemetry still doesn't reach the
   dashboard, deploy that observer (see dashboard README "Optional fleet
   telemetry") or add a loopback telemetry mirror.

### Access quick-ref
- SSH: `ssh -i ~/.ssh/id_ed25519_pi jbrascom@100.100.0.34` (tailnet) or
  `10.65.247.9` (RN03). Pi user `jbrascom`, passwordless sudo.
- Hotspot link drops on long SSH sessions — run long work as detached
  `systemd-run`/`nohup` units writing to a file, then read the file.
