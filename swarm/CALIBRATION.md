# Camera calibration and swarm test — run sheet

**Goal for the morning:** measure the four numbers per airframe that the shared
picture's accuracy entirely depends on — mount yaw, mount pitch-down, and the
horizontal and vertical field of view — then fly a three-platform cross-cue and
measure how closely the platforms agree.

**Why pitch-down first.** From the bench sweep, at the Cruza's real working
range of about 309 m (109 m AGL, 25° mount, 5.6° nose-up):

| Model error | Cruza (309 m) | quadpi (90 m) | rn03 (70 m) |
|---|---|---|---|
| heading off 1° | 5 m | 2 m | 1 m |
| heading off 5° | 27 m | 8 m | 6 m |
| **mount pitch off 1°** | **16 m** | 3 m | 3 m |
| **mount pitch off 5°** | **69 m** | 15 m | 12 m |
| relative altitude off 10% | 31 m | 9 m | 7 m |

Mount pitch costs about three times what heading does, and it is the error
nobody notices, because a mis-set mount is silently consistent. Ten degrees of
it puts the Cruza's point **348 m** out — nearly three times the 120 m fusion
radius, so it stops agreeing with the quad that they are looking at one object,
which is the whole capability. Five degrees (69 m) still lands inside the
radius, so the platforms would agree, just less precisely.

**This already bit us.** `swarm.SENSORS` carried 15° for the Cruza until the nose
sled design was checked on 27 Oct, which puts the AI Camera in the chin at **25°
down**. At the 20 Oct flight geometry (109 m AGL, 5.6° nose-up) a centred cue
resolved with 15° lands about **350 m beyond** the truth, because a shallower
assumed look-down stretches the range. That is nearly three times the fusion
radius — the Cruza would never have correlated with a quad. SENSORS now carries
25, but that is design intent for the printed nose, not a measurement of the
assembled one, which is what the rest of this document is for.

### The field of view is measured, never copied

The sled drawing captions a **52°** vertical view and the Raspberry Pi AI
Camera's published figure is about 52.3°, against the **49.0** configured on the
aircraft. Do not resolve that by typing 52 anywhere. **Phase 2 measures it, and
whatever it measures is what goes in.**

This is not pedantry, it is how the measurement works. `observe.py` reports an
angle, not a pixel:

```
el_rel_deg = (0.5 - cy) * vfov_deg
```

so every angle the aircraft reports is already denominated in its *configured*
field of view, and `calibrate.py fov` recovers the real lens as
`configured x measured-ratio`. Put an aspiration in the configured slot and the
answer is scaled by the very error you were trying to find — setting
`SENSORS` to 52 while the aircraft ran 49 would have made a true 52.3° lens
measure as **55.5°**, and nothing in the output would have looked wrong.

So:

- `SENSORS` holds what the aircraft is **configured** with, currently 49.0. It
  is a mirror of `observe.hfov_deg` / `vfov_deg`, not a claim about the lens.
  `swarm/test_swarm.py` fails if the two drift apart.
- Records now carry their own `"fov": [hfov, vfov]`, so a capture says what
  produced its angles and `fov` measures against that rather than against the
  table. Captures taken before this say so in the output.
- When phase 2 gives a number, change the Pi's `observe` config **and**
  `SENSORS` to it together, then re-run `solve` — the two measurements are
  coupled.

Until then the Cruza's vertical angles are off by whatever 49.0 is wrong by,
roughly 0.6° at 10° off boresight if the lens really is 52.3°.

Everything below is ordered by what buys the most accuracy per minute spent.

Nothing in this procedure transmits to an aircraft. The tools read the camera and
write to one loopback port.

---

## Tonight, before you stop

These are the things that cannot be fixed at 07:00.

1. **Ask ebach to authorise our key on quadpi.** This is the hard gate: quadpi is
   provisioned for `ebach` only, so the dashboard cannot open its observation
   tap. Without it the morning is a two-platform test. Our keys are
   `~/.ssh/id_ed25519_pi` and `rtic_pi_key` on alien03.
2. **Restart the dashboard.** The instance running as PID 28896 was started
   before the swarm changes and is serving the old code, with no `swarm` field
   and a single Cruza-only observer. Stop it and start it again.
3. **Copy `companion/observe-tap.py` to `/opt/cruza-observe-tap.py`** on quadpi
   and rn03. They have ordinary cameras, not an IMX500, so they need only the
   tap — not `deploy-observe.sh`, which requires the IMX500 stack and will
   refuse. The detector for those two is `swarmtest.py inject`.
4. **Drop `repeat_seconds` to 1.0** in the Cruza's `/etc/cruza/config.json`
   `observe` block. The default of 3.0 gives one record per class per three
   seconds, so a two-minute static capture yields 40 samples instead of 120. Put
   it back to 3.0 before flying.
5. **Charge everything** — aircraft packs, the ground radios and the Alfa.
6. **Note the Alfa's SSID.** It has roamed off `DoodleLabsWiFi-3cc462` onto
   `RN03` before and the symptom looks exactly like quadpi being down. Check it
   before diagnosing anything else.

## Gear

- Tape measure, 10 m or longer. **This is the precision instrument of the day** —
  a handheld GPS fix is good to 3–5 m and the ground baseline is only 4–7 m long,
  so a tape beats GPS by two orders of magnitude here.
- **A step ladder or anything that puts the camera about 2.6 m up.** See the
  geometry note below; this is not optional for a person-as-target calibration.
- Something to mark the exact ground spot: a cone, a stake, chalk.
- A bubble level, or better, a laptop running QGroundControl.
- A tape-measured height for whoever stands as the target, and a second person
  to run the capture.

---

## Phase 0 — the geometry, and the trap in it (read this first)

The detector reports the **centre of its bounding box**, and `swarm.py` places
that point on the ground. For a standing person the box spans head to feet, so
its centre sits at roughly **half their height**. In flight that is irrelevant:
at 100 m over a 309 m slant, a 0.85 m torso offset moves the angle by 0.13°. On
the ground at 4.5 m it moves it by **10.5°**, which would hand you a
pitch-down figure wrong by more than the error you came to remove.

So the working height is `camera height − box-centre height`, and the camera has
to be meaningfully above the target's torso:

| Camera height | Working height | Marker at, cruza | quadpi | rn03 |
|---|---|---|---|---|
| 1.2 m (table) | 0.33 m | 0.7 m | 0.6 m | 0.7 m |
| 1.8 m | 0.93 m | 2.0 m | 1.6 m | 2.0 m |
| **2.6 m (ladder)** | **1.73 m** | **3.7 m** | **3.0 m** | **3.7 m** |
| 3.2 m | 2.33 m | 5.0 m | 4.0 m | 5.0 m |

A table at 1.2 m puts the marker well under a metre from the lens, which is
useless. **Use the ladder.** The Cruza column comes from the nose sled design's
25 deg mount, so it is a real starting point rather than a guess; quadpi and
rn03 are still placeholders. Either way, walk the marker in or out until the
detection sits near the middle of the frame.

**The centred window is narrower than you might expect.** At 2.6 m with the
Cruza's 25 deg mount, `solve` accepts only samples between about **2.7 m and
5.7 m**; past that the target is more than 8 degrees off boresight and is
excluded. Stay inside that band unless you pass `--all-samples`. The solver
handles any position that is in frame; centring only keeps a field-of-view error
out of the mount result.

Accuracy you can expect at 2.6 m, from getting the box-centre height wrong:

| Box centre off by | Mount error | → ground error at 309 m |
|---|---|---|
| 5 cm | 0.63° | 10.5 m |
| 10 cm | 1.26° | 20.3 m |
| 20 cm | 2.48° | 38.1 m |

This got *worse* when the mount was corrected to 25 deg, because the marker now
stands at 3.7 m rather than 6.5 m and the same vertical error is a bigger angle
at shorter range. Measure the target person's height and halve it; ±10 cm
leaves about 20 m at operational range, against the **348 m** that the old
15 deg figure would have cost.

**Level the airframe against the autopilot, not against the ground.** The
pitch-down angle must be measured in the frame the EKF calls level, because that
is the frame `swarm.py` works in. Easiest: connect QGroundControl and shim the
airframe until ArduPilot reports pitch 0.0 and roll 0.0. If you cannot get it to
zero, read the reported pitch and pass it as `--pitch`; do not guess from a
bubble level on the fuselage.

---

## Phase 1 — static mount calibration, per airframe (~15 min each)

Do the Cruza first. It has the longest operating range, so it gains the most.

1. Set the airframe on the ladder, powered, camera clear. Level it against the
   autopilot as above and write down the reported pitch.
2. **Sight along the fuselage centreline and put the marker on that line.** This
   is the second trick of the day: with the marker dead ahead, the reported
   azimuth *is* the mount yaw with the sign flipped, so the compass never enters
   the measurement. If you cannot get it exactly on the line, measure how far
   right of it the marker sits and pass that as `--offset` (negative for left).
3. Measure and write down, in centimetres:
   - `height` — ground to the **lens centre**
   - `distance` — lens to marker, horizontal, along the nose line
   - `offset` — marker right of the nose line, if any
   - the target person's height, halved, as `target-height`
4. Have the target stand on the marker, still, facing the camera.
5. Capture. On the aircraft's Pi, with the dashboard **closed** so nothing else
   is holding the port:

   ```bash
   python3 calibrate.py capture --port 15620 --out ~/cal-cruza.jsonl --seconds 150
   ```

   Make sure the detector is actually running (`systemctl status cruza-observe`
   on the Cruza). Two sockets on one UDP port steal packets from each other
   rather than both receiving, so close the dashboard — do not try to share.
6. Watch the progress lines. You want 25 or more records. If none arrive, the
   target is not being detected: check the class is in the `observe` config's
   `classes` list and that the score clears `min_score` (0.55).
7. **Move the marker to a second, clearly different distance** — for the Cruza
   use about **3.0 m and 5.5 m**, both inside the centred window — and capture
   again to a second file. This is the cross-check that validates your
   target-height number, and it costs five minutes. (The 4 m / 9 m pair that
   suited the old 15 deg assumption no longer works: at 9 m the target sits
   14 deg off boresight and `solve` drops it.)
8. Pull both files to the laptop and solve each:

   ```bash
   python swarm/calibrate.py solve --source cruza \
     --records cal-cruza-near.jsonl \
     --height 2.60 --distance 3.00 --target-height 0.87 \
     --reference-range 310 --out swarm/cal-cruza-near.json
   ```

9. **Compare the two distances.** If `pitch_down` agrees within about half a
   degree, your target height is right and you can trust the number. If they
   disagree, `--target-height` is wrong, and which way tells you how to fix it —
   the near reading always moves more, because the same vertical error is a
   bigger angle at short range:

   | Two-distance result | What it means | Do this |
   |---|---|---|
   | near **higher** than far | you assumed the box centre **too low** | raise `--target-height` |
   | near **lower** than far | you assumed it **too high** | lower `--target-height` |
   | near == far | correct | use the number |

   Worked for the 3.0 / 5.5 m pair, with the truth at 0.87 m and a real
   pitch-down of 25.0°: assuming 0.72 m reads 27.10° near and 26.41° far
   (+0.69 apart); assuming 1.02 m reads 22.80° and 23.57° (−0.76 apart);
   assuming 0.87 m reads 25.00° at both.
   Re-solve both files at adjusted values until they agree — the data does not
   need recollecting, so this is a laptop job, not a field job.
10. Paste the suggested block into `swarm.SENSORS` in
    [dashboard/swarm.py](../dashboard/swarm.py). The tool prints it ready to go.

Repeat for quadpi and rn03. For those two the "detector" is whatever their
camera stack reports; if they have no detector at all, skip their static
calibration — an injected cue carries the mount angles you give it, so an
uncalibrated mount on those airframes only matters once they have a real camera
feeding the tap.

**Then re-run the bench** so the sensitivity table reflects the real airframes:

```bash
python swarm/swarmtest.py bench --log logs/2026-10-20/download-162053_202463/log_00030.records.json --out swarm/bench-after-calibration.json
```

## Phase 2 — field of view (~15 min, do it, do not skip it)

**Do not skip this because the lens is "documented".** The Cruza's is documented
twice, at 49.0 and at 52.3, and the number the aircraft is configured with is
the one every reported angle is denominated in. Measure it. Whatever comes out
is what goes on the Pi and in `SENSORS`; nothing gets typed in from a drawing.

Phase 1 put the marker at the boresight, where a field of view leaves no trace.
This phase deliberately puts it **off centre on both axes at once** — further
out, so it rides high in the frame, and off to the side. `fov` needs a sample
past a quarter of the way to each edge:

| | threshold off boresight | why |
|---|---|---|
| hfov | 8.2° | `hfov x EDGE_FRACTION / 2` |
| vfov | 6.1° | `vfov x EDGE_FRACTION / 2` |

**From the 2.6 m ladder, put the marker 5.5 m out and 1.0 m to the right.** That
is +10.3° azimuth and +7.8° elevation off boresight, clearing both thresholds
with enough margin that a lens up to about 10% wider than configured still
reports inside them.

> The geometry this file recommended before 27 Oct — 3.7 m out, 0.55 m across —
> measured **neither** axis. At 3.7 m the marker sits on the boresight by
> construction, so the vertical sample is 0.2°, and 0.55 m across is 8.5° true
> but reports as 7.8° through a wider lens, under the horizontal threshold too.
> `fov` now says so and names both thresholds instead of only the horizontal one.

Sight the nose at a point 1.0 m left of the marker so the yaw from phase 1 still
applies, capture 10-20 detections, then:

```bash
python swarm/calibrate.py fov --source cruza --records cal-cruza-edge.jsonl \
  --cls person --height 2.60 --distance 5.50 --offset 1.00 --target-height 0.87 \
  --yaw <from phase 1> --pitch-down <from phase 1>
```

It prints the truth angles it derived from your tape, then each axis as
`configured -> measured`. Within 2% of the configured value, leave it alone.

**When you change a field of view, change it in two places and re-run phase 1.**
The Pi's `observe` config block (`hfov_deg` / `vfov_deg`) is what computes the
angles; `swarm.SENSORS` must mirror it, and `swarm/test_swarm.py` fails if the
two drift apart. Then re-run the mount solve — it reads angles the field of
view scales, so the two measurements are coupled.

Records captured by a current `observe.py` carry their own `"fov": [h, v]`, and
`fov` measures against that rather than against `SENSORS`. If your capture
predates that, the output says so; believe it less.

---

## Phase 3 — the flight test

Design the flight to measure, not just to demonstrate.

**Set the truth point.** One agreed spot both aircraft can see: a parked vehicle
is ideal, since `car` is in the class list and it is unambiguous. Fix its
position as well as you can — a phone GPS averaged over two minutes is about
±2 m, which is plenty against a 120 m fusion radius. Write it down.

**Fly the Cruza in an orbit around the truth point, not a straight pass.** This
is the one thing that makes the flight data better than the ground data: mount
yaw and a compass bias are the same number if every observation is taken on one
heading, and they separate only when the headings differ. `solve` reports the
heading spread and warns you below 90°. An orbit gives you 360°.

**Do two altitudes** — say 80 m and 120 m. The range comes from
`altitude / tan(depression)`, so two heights test that model rather than assuming
it.

**Put quadpi and rn03 on the same truth point, at the same time,** from different
directions, each at a measured offset. Simultaneity is the point: `span_m` only
exists when two platforms report the same object at once.

**Add a second, distinct object about 500 m from the first**, and confirm it
stays a separate track. A fusion radius that merges everything is worse than no
fusion.

With the dashboard open, inject from the platforms that have no detector:

```bash
python3 swarmtest.py inject --source quadpi --port 15621 \
  --lat <truth lat> --lon <truth lon> \
  --aircraft-lat <its lat> --aircraft-lon <its lon> --agl 60 --heading 45 \
  --count 30 --rate 2
```

Afterwards, pull the Cruza's flight log and solve against the real track, which
is the best mount number you will get:

```bash
python swarm/calibrate.py solve --source cruza --records cal-flight.jsonl \
  --log logs/<date>/<download>/log_000NN.records.json \
  --lat <truth lat> --lon <truth lon> --reference-range 310
```

### Pass criteria

| Check | Target | Where to read it |
|---|---|---|
| Mount solve scatter | under 1° std dev | `solve` output |
| Near vs far distance agreement | within 0.5° | two `solve` runs |
| Heading spread in flight | 90° or more | `solve` output |
| Cruza geolocation vs truth | within 40 m at ≤350 m | `solve`, or the map |
| Quad geolocation vs truth | within 15 m at ≤100 m | the map |
| Two platforms on one object | `span_m` under 50 m | the AOI row's "N m apart" |
| Two objects 500 m apart | two separate tracks | the AOI panel |
| Field of view measured, not assumed | both axes reported | `fov` output |
| Pi config and `SENSORS` agree | test passes | `python swarm/test_swarm.py` |
| Bench after calibration | 12/12 | `swarmtest.py bench` |

`span_m` is the honest live check and needs no post-processing: if two aircraft
looking at one agreed point disagree by more than about 50 m, a mount angle is
still wrong, and the panel is telling you so in the field.

### If it goes wrong

- **No records at all** — the class is not in the `observe` config's `classes`
  list, the score is under `min_score`, or the dashboard is holding the port.
- **`No records could be matched to an aircraft state`** — the Pi clock and the
  flight log disagree. Check the Pi has NTP, or widen `--tolerance`.
- **Pitch-down looks absurd** — you almost certainly have `--target-height`
  wrong, or the log does not contain the launch point so the relative altitude
  is wrong. For the latter, pass `--ground-alt`; the tool warns when the
  altitude span is under 10 m.
- **`solve` warns about frame centre** — all the data is off-boresight, so a
  field-of-view error is folded in. Re-capture with the target centred.
- **A cue shows no bearing on the dashboard** — that aircraft's telemetry is not
  reaching the dashboard. The panel deliberately leaves a cue unlocated rather
  than placing it with another aircraft's heading.
