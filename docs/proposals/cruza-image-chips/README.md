# Proposal for jbrascom: image chips from the Cruza detector

**For your review. Nothing in your code has been changed.** This patch is only
a suggestion. Apply it, change it or decline it as you see fit. ebach's
dashboard works either way: without chips the handover card just says "No
image received".

## Why

ebach's dashboard now has a **Mission handover** panel. Each geolocated cue
from your observers waits there for the operator to approve or deny handing it
to a live aircraft (quadpi / TFW drone), and the decision is logged. The
operator decides much better with a picture of what the camera saw, and the
only thing missing for that is an image from the Cruza.

## What the patch does (`observe-chips.patch`, against `companion/observe.py`)

- Adds `observe.chips` (default **false**) and `observe.chip_seconds`
  (default 20) to the config. With chips off, the output is byte-for-byte what
  it is today.
- With chips on, after a detection record is published, it sends a small
  JPEG (box plus margin, about 160×120, quality 70, about 2–10 KB) as numbered
  parts. It sends one with the first record of a class, then at most every
  `chip_seconds` per class:
  ```json
  {"t": 1793150000.12, "chip": 93, "part": 0, "parts": 9, "jpg": "<base64, ≤400 chars>"}
  ```
  `chip` is the `seq` of the detection record it shows.
- **Every part is its own datagram under your existing 512-byte cap**, so
  `observe-tap.py` (and its installed sha256) does not change, and neither
  does the dashboard's reader.
- `Publisher.send()` now returns the `seq` it used. The picture comes from
  `picam2.capture_array("main")`, one frame after inference. Any failure there
  is logged and skipped, so it can never stop detection.
- `--synthetic` also sends plainly labelled "SYNTHETIC" chips when chips are
  on, for bench tests.

## Verified on ebach's laptop (no camera)

Ran the patched `observe.py --synthetic 4` with chips on into **your
unmodified `observe-tap.py`**, and read the framed output with the
dashboard's receiver. 36 frames, largest 465 bytes, and all four detections
(person, car, truck, boat) arrived with a valid JPEG. **Not tested on the Pi
or with the IMX500.** Things to check there:

- `capture_array("main")` on your preview configuration returns 4-channel
  XBGR; the patch keeps the first three channels. Check the colours look right.
- Box coordinates are in the network's input space; the 50% margin covers the
  small offset to the full frame. `imx500.convert_inference_coords()` would
  make it exact if you prefer.
- CPU on the Zero 2 W: one 160×120 JPEG every 20 s per class should be noise,
  but worth a look alongside video.
- If Option C (one camera owner in `stream.py`) lands, the same
  `chip_jpeg()` / `send_chip()` pair can move there, and the image then
  comes from the exact frame inference ran on.

## A second, related suggestion (no patch): placing cues

`swarm.picture()` places every cue still in the store using the reporting
aircraft's *current* heading and position. A cue last seen several seconds
ago on a turning Cruza is re-projected with the new heading, so it moves on
the map. In a bench simulation (Cruza on a 400 m orbit at ~16 m/s), one parked
car became five areas of interest between 550 and 832 m away. The
areas-of-interest panel shows the same effect.

Suggested fix: geolocate each record **when it arrives** (or with telemetry
matched to its `t`) and keep that position on the store entry. ebach's
handover queue works around it for now by only taking cues seen in the last
2 s, so this is not urgent for the handover feature. It would make your panel
and the cross-cueing tighter.

## Apply / revert

```bash
git apply docs/proposals/cruza-image-chips/observe-chips.patch
```

Then set `"chips": true` in the `observe` block of `/etc/cruza/config.json` on
the Cruza when you want it. To undo: `"chips": false`, or `git checkout
companion/observe.py`.

## Update, 28 Oct 2026 evening: applied to `stream.py` on the Cruza

With jbrascom's agreement the chips were added to the service that now owns the
camera, `/opt/cruza/stream.py` (`cruza-observe` is disabled). The change as
deployed is `../cruza-2026-10-28/stream-image-chips.patch`, against the version
that was on the Cruza (which is older than `companion/stream.py` in the repo:
it lacks the `fov` field). Enabled with `"chips": true` under `"observe"` in
`/etc/cruza/config.json`, one chip per class at most every 10 s.

What differs from the `observe.py` proposal:
- The main stream is actually 1280x720 XBGR8888, so the chip is cut from RGBX
  and encoded with `simplejpeg` (YUV420 is also handled).
- The detection box is mapped into the main stream with
  `imx500.convert_inference_coords`, since the network sees the whole sensor
  and the main stream is a 16:9 cut of it.
- Side finding: `picam2.start_recording(encoder, FileOutput(...), config)`
  passes the configuration as `pts`, so the requested 640x480 is ignored and the
  camera runs at its 1280x720 default. Pass `config=config` (or call
  `picam2.configure(config)` first) if 640x480 is wanted.

Undo is in `~/CHANGES-2026-10-28.txt` on the Cruza.
