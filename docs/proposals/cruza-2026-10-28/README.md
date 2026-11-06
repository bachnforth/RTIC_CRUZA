# Cruza handover for jbrascom — 28 Oct 2026

On the evening before the 28 Oct flight test, with your OK, ebach's session made
five changes **directly on the Cruza** (tfwcruza1, 100.100.0.34) to get video,
detections and telemetry through to the dashboard. They are live on the
aircraft but **none of them is in your files in the repo** (`companion/`), so a
redeploy from the repo would undo some of them. Nothing in `companion/` was
edited; this folder is for you to review and fold in as you see fit.

Every change has an undo, listed in `~/CHANGES-2026-10-28.txt` on the Cruza
(copied here as [CHANGES-2026-10-28.txt](CHANGES-2026-10-28.txt)), and the
original files are kept beside them as `*.bak-2026-10-28`. The flight
controller, its parameters and arming were not touched.

## What was wrong, and what was done

| # | Symptom | Cause | Change on the Cruza |
|---|---|---|---|
| 1 | Detector failed at boot ("Pipeline handler in use by another process"); video came and went | `cruza-stream` (video + detections, your Option C) and the old `cruza-observe` were **both enabled** and raced for the IMX500 at every boot | `cruza-observe` disabled; `cruza-stream` owns the camera |
| 2 | SSH hung, telemetry gaps, Pi very slow after boot | Pi Zero 2 W (415 MB) booting a desktop nobody uses; 217 MB into swap | Default target `multi-user` (no desktop). LTE (`cruza-lte`) and Wi-Fi connections are system-wide, checked first |
| 3 | (same) | Desktop-install services running | `packagekit`, `udisks2`, `nfs-blkmap`, `rpcbind` disabled. Swap use fell to ~79 MB |
| 4 | Dashboard showed the Cruza **offline** although frames were arriving | `/opt/cruza-telemetry-tap.py` thins to one message per *type* per 0.5 s. With a phone GCS connected, its 1 Hz heartbeat arrived just before the autopilot's and the autopilot heartbeat was dropped every time | Thinning keyed per sender + type: [telemetry-tap-per-sender.patch](telemetry-tap-per-sender.patch) |
| 5 | Handover cards had no picture to review | Nothing sent images | `/opt/cruza/stream.py` sends a small JPEG of each detection (≤ 1 per class per 10 s), enabled by `"chips": true` under `"observe"` in `/etc/cruza/config.json`: [stream-image-chips.patch](stream-image-chips.patch) |

Verified on the bench the same evening: steady telemetry (heartbeat < 1 s,
GPS fix, 25+ satellites), video to the dashboard, person detections becoming
handover requests, and a real 5.6 KB picture of the person on the card.
On 29 Oct, after a reboot, all five changes were still in place, and the
corrected crop (item 5's `convert_inference_coords` mapping) was checked with a
real detection: the person stood off to one side of the frame, and the 4 KB
picture on the card showed them centred, head to feet. **Not yet verified:**
any of it in flight.

## Required actions for you

1. **Fold the telemetry-tap fix into your deployed source.** The repo's
   `companion/telemetry-tap.py` is an older (AF_PACKET) version than the one on
   the Cruza, so the patch is against the deployed file. Without this, any
   redeploy of the tap brings the "Cruza offline while a phone GCS is
   connected" problem back.
2. **Fold the image-chip change into `companion/stream.py`** (or tell ebach to
   turn it off with `"chips": false`). The patch is against the deployed
   `stream.py`, which is older than the repo's: it lacks the `fov` field you
   added. The chip code catches its own errors, so a failure can never stop
   video or detections; failures are logged as `chip_error`.
3. **Make sure nothing re-enables the old camera services.**
   `companion/enable-video-autostart.sh` enables `cruza-video` (rpicam), and
   `deploy-observe.sh` tells the reader to enable `cruza-observe`; either one
   would take the camera from `cruza-stream` again. The repo's
   `systemd/cruza-video.service` and `cruza-observe.service` also still run as
   `User=ebach`, which does not exist on the reflashed image.
4. **Decide whether the Cruza should keep booting without the desktop.** If you
   use VNC or the desktop on the bench, undo item 2 on the bench and redo it
   before flying; the memory difference is large on a Zero 2 W.
5. **Optional bug in `stream.py`:** `picam2.start_recording(encoder,
   FileOutput(gst.stdin), config)` passes the configuration as the `pts`
   argument, so the requested 640×480 is ignored and the camera runs at its
   1280×720 XBGR8888 default (seen in the `chip_error` logs while debugging).
   Pass `config=config`, or `picam2.configure(config)` first, if 640×480 was
   intended; the encoder then has much less to do. Detection angles assume the
   main stream's FOV, so this affects calibration too.

## Things worth knowing

- The cellular link was the weak point all evening: Tailscale pings swung from
  0.2 s to 3 s and SSH often timed out during the banner. With `cruza-stream`
  now working, ~300 kbps of video goes to each phone in `android_ip` /
  `android_ip2` plus the dashboard's copy; on a weak uplink that delays
  telemetry. If telemetry is patchy in the field, consider one phone or a lower
  profile.
- `cruza-stream` restarts take about a minute while the IMX500 loads its
  network firmware.
- The dashboard side (handover queue, image reassembly, approve/deny) is in
  ebach's files only; see [../../mission-handover-2026-10-27.md](../../mission-handover-2026-10-27.md).
