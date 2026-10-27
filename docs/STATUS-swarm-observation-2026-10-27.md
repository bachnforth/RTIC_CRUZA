# Swarm observation — where this stands, 27 Oct 2026

**One decision is needed before this moves, and it is ebach's call.** Everything
else is either done and verified, or blocked behind it. Handing the lead over.

---

## The decision: on the Cruza it is video **or** detections, never both

`cruza-observe.service` is installed, correctly configured and enabled. It
cannot start:

```
V4L2 'imx500 10-001a': Unable to set controls: Device or resource busy
IMX500: Unable to set network firmware ...fpnlite_320x320_pp.rpk: [Errno 16] Device or resource busy
```

`cruza-stream.service` (PID 1357, `/opt/cruza/stream.py`) owns the camera —
confirmed with `fuser -v`, it holds `/dev/video0,1,11,13,14,15,16` and both
`/dev/media0` and `/dev/media2`. There is one IMX500 and it takes one owner.

**Stopping the video is not just a dashboard cost.** Per `/etc/cruza/config.json`,
`cruza-stream` feeds `android_ip` **100.100.0.60** and `android_ip2`
**100.100.0.57** on port 5600 — both pilots' Android QGC feeds — plus
`video_mirror_port` 15600 for the dashboard. Killing it blinds the pilots, which
is why nobody has made that call unilaterally.

### The three ways out

| Option | Gets you | Costs you |
|---|---|---|
| **A. Stop `cruza-stream`, run the detector** | Real Cruza detections, and camera calibration can start | Both pilot QGC feeds and dashboard video, until it is switched back |
| **B. Keep video, no Cruza detections** | Pilots keep their feeds | No real cues from the Cruza; cross-cue testing only via `inject` |
| **C. One camera owner — the actual fix** | Both, permanently | A contained piece of work on `stream.py` |

**Option C is the right answer and is not large.** picamera2 with an IMX500
returns **frames and inference metadata from the same stream** — that is how the
stock Raspberry Pi demos work. Detection belongs *inside* `stream.py`: one
process owning the camera, publishing video to 5600/15600 and advisory records
to loopback 15620, instead of two services fighting over `/dev/media0`. Until
that exists, A and B are a straight trade.

Current state: `cruza-observe.service` left **enabled and inactive**, failed flag
cleared with `reset-failed`. While video keeps running it will retry and fail on
each boot. Disabling it is one command if that noise is unwanted.

---

## Verified, with evidence

**TFW drone (rn03)** — ready, end to end.

- `/opt/cruza-observe-tap.py` installed, `root:root 644`, sha256
  `695441dd…7035` matched at source, staged and installed. Survived a reboot.
- Injector staged at `~/rtic-swarm/` in the two-directory layout `swarmtest.py`
  requires (`swarm/swarmtest.py` + `dashboard/swarm.py` +
  `dashboard/observations.py` — it does `sys.path.insert(HERE.parent/'dashboard')`,
  so one file is not enough).
- The **full chain was proven on the aircraft**: real `inject` → real tap →
  two-byte framing → store → geolocation. 3/3 records, **0.00 m from truth**.
- The dashboard's *exact* SSH invocation works, including that it passes
  `HostKeyAlias=100.100.0.6` rather than an ssh-config alias.

**Cruza** — flying telemetry is good, camera is not available.

- Telemetry live: GPS 3D fix, 7 satellites, position, heading 168.5°, pitch 1.6°,
  video receiving. It **can** geolocate a cue the moment one exists.
- `PreArm: Battery 1 below minimum arming voltage` — charge before flying.
- Reachable on the tailnet via DERP relay (350 ms–1 s). It was **not** reachable
  on the RN03 hotspot `10.65.247.9` this session. Tailscale's status line
  claiming `tfwcruza1` was "offline, last seen 16h" was stale — ignore that
  column alone.

**Dashboard** — restarted on the new code (PID 21328). `/status` serves the
`swarm` field (`fuse_radius_m` 120) with three observation readers, three fleet
sources and three video feeds.

One cosmetic trap worth not re-diagnosing: with no detector publishing,
`observe-tap.py` self-exits after 30 s idle by design, so the reader shows a
30-second reconnect loop reporting **"Video connection closed"**. That string
comes from a helper shared with the video feed and is misleading in an
observation reader. Empty error with `connected=False` is the healthy idle state.

## Reported but **not** verified from here

**quadpi** — ebach reports the tap is installed and the key added:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJRYJxUuXPcAfTjtpKvdCoPop1McHjhF3czGxNbyN//q windows-claude-to-pi
```

quadpi went fully offline before this could be confirmed — `tailscale ping`
timed out, not just SSH, so the node is down rather than refusing us. Earlier
today it *was* up and reachable, and its sshd read our key's fingerprint and
declined it; that rules out the fail2ban/`MaxStartups` resets seen on 21 Oct.
**Next time it is powered, one command settles it:**

```bash
ssh -i ~/.ssh/id_ed25519_pi -o IdentitiesOnly=yes ebach@100.100.0.10 'hostname; sha256sum /opt/cruza-observe-tap.py'
```

Expect `695441dd305a71c63d8c8d4701f3c11891ca5c120d09f6bf5b88c31eb0cc7035`.

---

## Next step is camera calibration — and it is gated

Calibration is the right next move: mount pitch is the dominant error term, worth
about **16 m per degree at the Cruza's 309 m working range** — roughly three
times what a heading error costs, and the one nobody notices, because a mis-set
mount is silently consistent. The procedure, tooling and tests are all ready in
[`swarm/CALIBRATION.md`](../swarm/CALIBRATION.md) and `swarm/calibrate.py`.

**An earlier version of this document quoted 65 m per degree at 660 m. That was
wrong, and the reason matters.** `swarm.SENSORS` carried 15° of camera
mount-down for the Cruza until the nose sled design was checked: the AI Camera
sits in the chin at **25° down**. At the 20 Oct flight geometry a centred cue
resolved with 15° lands
**348 m** beyond the truth, because a shallower assumed look-down stretches
`altitude / tan(depression)`. That is nearly three times the 120 m fusion radius
— the Cruza would never have correlated with a quad, and it would have looked
like the quads were wrong. Corrected in #3, with every table re-derived and the
bench re-run. The steeper real mount also shortens the working range from 657 m
to 309 m, which is why the per-degree cost is now lower than previously stated.

These are design intent for the printed nose, not a measurement of the assembled
one — which is exactly what calibration is for.

**The field of view is a measurement, and nothing has measured it.** The sled
drawing captions 52°, the AI Camera's published figure is about 52.3°, and the
Pi's `observe` config says `vfov_deg: 49.0`. The temptation is to settle that by
typing 52 into `swarm.SENSORS`, and #3 briefly did. That is worse than leaving it
alone, because `observe.py` reports `el_rel_deg = (0.5 - cy) * vfov_deg` — every
angle the aircraft sends is already denominated in the *configured* field of
view, and `calibrate.py fov` recovers the real lens as `configured x ratio`. Set
`SENSORS` to 52 while the aircraft runs 49 and a true 52.3° lens measures as
**55.5°**, with nothing in the output looking wrong.

So `SENSORS` is back to 49.0, mirroring the aircraft, and a test fails if the two
drift apart. Records now carry their own `"fov": [h, v]` so a capture states what
produced its angles. Phase 2 of the run sheet measures it; whatever it measures
goes on the Pi and in `SENSORS` together, and then phase 1 is re-run, because the
mount solve reads angles the field of view scales.

Until then the Cruza's vertical angles are off by whatever 49.0 is wrong by —
roughly 0.6° at 10° off boresight if the lens really is 52.3°.

**But it cannot start today on any platform**, which is worth being plain about:

- **Cruza** — calibration needs the detector reporting angles for a marker. The
  detector cannot run while video does. Blocked behind the decision above.
- **quadpi and rn03** — ordinary cameras, no detector at all. `inject` carries
  whatever mount angles it is given, so there is nothing to calibrate *from*.

So the order is: settle the camera-owner question → run the Cruza ground
calibration (step ladder, tape, ~15 minutes) → fly the cross-cue test.

Nothing else is waiting on anything. The shared picture, the fusion, the test
harness and the calibration tooling are written, tested (130 tests) and pushed.

## Safety boundary, unchanged

There is still **no MAVLink sender anywhere in this system**. A correlated track
is a better reason for a human to look somewhere, not a decision. An operator
confirms or dismisses each cue and a confirmed one only drops a candidate point
into the existing preview-only command panel.
