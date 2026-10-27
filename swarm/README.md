# Swarm observation test — can three aircraft share one picture?

**Question this answers:** when the Cruza, the TFW drone (rn03) and the quad each
report what their camera sees, does the architecture turn that into *one* picture
with usable positions — and does it notice when two of them are looking at the
same thing?

That second half is the swarm effect worth having. One aircraft saying "something
at bearing 121, about 300 m out" is a guess. Two aircraft independently putting
the same class of object in the same 100 m of ground is a reason to go look.

**Nothing in this folder, or in the code it tests, transmits to an aircraft.**
There is no MAVLink sender anywhere in this system and this work does not add
one. Detections are advisory cues; an operator confirms or dismisses each one on
the dashboard, and a confirmed cue only drops a candidate point into the existing
preview-only command panel. Correlating two aircraft's reports makes the cue
*better evidence for a human*, not a decision. If a future change is asked to
make a detection task or engage anything by itself, that is the line.

## What the architecture does now

```text
Cruza  IMX500 -> observe.py ---\
quadpi camera -> (publisher)  --> loopback UDP 1562x -> observe-tap.py
rn03   camera -> (publisher)  ---/                           |
                                                       SSH stdout
                                                             v
                                    server.py Observe (one reader per aircraft,
                                    tags each record with ITS OWN aircraft name)
                                                             v
                                    observations.ObservationStore  (validated,
                                    bounded, expiring, one entry per source)
                                                             v
                                    swarm.py  geolocate each cue from the
                                    reporting aircraft's telemetry, then fuse
                                    same-class cues within 120 m
                                                             v
                                    /status  ->  "Areas of interest" panel
                                                 operator Confirm / Dismiss
                                                 -> preview-only candidate point
```

What changed to make the test possible, because the old path could not do it:

- The store was keyed by class and bearing alone, so two aircraft reporting the
  same class at the same angle collided into one entry. Records are now tagged
  with the reporting aircraft, supplied by the reader that owns the SSH session —
  **a datagram cannot claim to be from another aircraft.**
- Geolocation lived only in the browser and hardcoded the Cruza's heading, pitch
  and height. A quadpi cue resolved that way would have been placed somewhere
  entirely wrong. It now happens in `dashboard/swarm.py`, per source, with that
  airframe's own camera model in `swarm.SENSORS`.
- There was no correlation at all. `swarm.fuse` does single-link clustering per
  class and reports `sources`, `cross_cued` and `span_m` — how far apart the
  contributing aircraft put the same object, which is the honest measure of how
  much to trust the point.
- `server.py` ran one Cruza-only reader. `OBSERVE_SOURCES` now lists all three.

## Results, 26 Oct 2026 (bench, real flight track)

`swarm/bench-report-2026-10-27.json` (and `-10-26`, before the mount was
corrected), flown against the Cruza's real 20 Oct
log (`logs/2026-10-20/.../log_00030.records.json`), mid-flight sample:
33.734325, -85.921209 at 109 m AGL, heading 121, pitch 5.6.

**12/12 checks PASS.** The chain carries geolocated detections from three
platforms into one picture, correlates them, keeps distinct objects distinct,
survives an aircraft going dark, drops malformed records and unknown sources,
and resolves 150 reports in 0.5 ms.

The number that matters is not the pass. It is this:

| Model error | Cruza (309 m) | quadpi (90 m) | rn03 (70 m) |
|---|---|---|---|
| heading off 1° | 5 m | 2 m | 1 m |
| heading off 5° | 27 m | 8 m | 6 m |
| **mount pitch off 1°** | **16 m** | 3 m | 3 m |
| **mount pitch off 5°** | **69 m** | 15 m | 12 m |
| relative altitude off 10% | 31 m | 9 m | 7 m |

**Camera mount pitch is the dominant error term** — about three times what
heading costs, and the one nobody notices, because a mis-set mount is silently
consistent. The range comes out of `altitude / tan(depression)`, so the shallower
the look-down the more a tilt error stretches it.

**These figures were themselves corrected on 27 Oct.** `SENSORS` carried 15° for
the Cruza until the nose sled design was checked: the AI Camera sits in the chin
at **25° down** with a **52° vertical view**. At the 20 Oct geometry that mistake
put a centred cue **348 m** beyond the truth — nearly three times the fusion
radius, so the Cruza would never have correlated with a quad. The steeper real
mount also shortens the working range from 657 m to 309 m, which is why every
number above is smaller than it used to be.

The operational reading is the concept of employment the fleet already assumed:
**the Cruza's cue is a direction to go look, not a location.** The close-in
platform's cue is the location. Fusing the two is what makes the pair worth more
than either, and it only works if the mounts are measured.

So, before trusting a cross-cue in the field:

1. Measure `pitch_down` and `yaw` on each airframe and set them in
   `swarm.SENSORS`. One degree of pitch is worth more than five of heading.
2. Check `hfov_deg` / `vfov_deg` against the actual lens, in the Pi's
   `observe` config block. The harness assumes the configured value is true.
3. Re-run `bench` after changing either; the sensitivity rows will show it.

**[CALIBRATION.md](CALIBRATION.md) is the field procedure for all of that** — the
tape-measure method, the step-ladder geometry, the standing-person torso trap
that would otherwise throw the ground measurement out by 10 degrees, and the
flight profile that separates mount yaw from compass bias. `calibrate.py` does
the arithmetic:

```bash
# Ground: nose sighted at the marker, everything measured with a tape.
python swarm/calibrate.py check --source cruza --height 2.60 --target-height 0.87
python swarm/calibrate.py solve --source cruza --records cal-cruza.jsonl   --height 2.60 --distance 4.00 --target-height 0.87 --reference-range 660
```

## Files

| File | Runs on | Purpose |
|---|---|---|
| `CALIBRATION.md` | — | **field run sheet: calibrate the cameras, then fly the test** |
| `swarmtest.py` | laptop, or an aircraft's Pi | `bench`, `inject`, `track` (below) |
| `calibrate.py` | laptop, or an aircraft's Pi | `solve`, `fov`, `check`, `capture` — measures the four numbers above |
| `test_calibrate.py` | laptop | 46 tests: the solver, the tape geometry, the target-height trap |
| `test_swarm.py` | laptop | 37 unit tests: geolocation, round trip, fusion, source isolation |
| `test_status.py` | laptop | starts the real `/status` handler and asks it for the picture |
| `test_panel.cjs` | laptop (node) | the browser panel, incl. "never place a quadpi cue with Cruza telemetry" |
| `bench-report-2026-10-26.json` | — | the run above, kept for comparison |

Run everything:

```bash
python swarm/test_swarm.py && python swarm/test_calibrate.py && python swarm/test_status.py && node swarm/test_panel.cjs && python -m pytest dashboard -q && node dashboard/test_map.cjs
```

Two suites in this repo fail on this laptop for reasons that predate this work
and are not about the swarm picture: `companion/test_cruza.py` reads
`config.example.json` by relative path, so run it from `companion/`; and
`linktest/test_linktest.py` calls `os.nice`, which does not exist on Windows —
that tool runs on the Pi.

## Bench — no aircraft, no network

Places a target at a known lat/lon, computes the angles each aircraft's camera
*would* report from its real position and attitude, emits exactly the record
`companion/observe.py` publishes, pushes it through the real store and resolver,
and compares the resulting point back to the truth it came from.

```bash
python swarm/swarmtest.py bench --log logs/2026-10-20/download-162053_202463/log_00030.records.json --out swarm/bench-report.json
```

Without `--log` it uses a synthetic 100 m / level-flight Cruza state, which is a
kinder geometry — always quote a result flown against a real log.

```bash
python swarm/swarmtest.py track logs/2026-10-20/download-162053_202463/log_00030.records.json
```

summarises a log so you can pick the window you want to fly the test at.

## Live — the real wire, on the aircraft

The bench proves the maths and the plumbing. It does **not** prove the link. Run
this when the aircraft are up to exercise the real path: Pi loopback →
`observe-tap.py` → SSH framing → `server.py` → store → picture → panel.

Per aircraft, once:

1. Install the tap. On the Cruza, `sudo bash ~/companion/deploy-observe.sh`
   installs the detector and the tap together (it requires the IMX500 stack).
   **quadpi and rn03 have ordinary cameras, no IMX500**, so they need only
   `/opt/cruza-observe-tap.py` — copy `companion/observe-tap.py` there — plus a
   publisher. For a capability test the publisher is `swarmtest.py inject`.
2. Confirm the port matches `OBSERVE_SOURCES` in `dashboard/server.py`:
   cruza 15620, quadpi 15621, rn03 15622.
3. Measure the camera mount and set it in `swarm.SENSORS`. See the table above
   for why this is not optional.

Then, with the dashboard open so the viewer lease is live:

```bash
# On each aircraft's Pi, pointing at ONE agreed truth point.
# --lat/--lon are the target; --aircraft-* and --heading are that aircraft's own state.
python3 swarmtest.py inject --source quadpi --port 15621 \
  --lat 33.7312 --lon -85.9151 \
  --aircraft-lat 33.7307 --aircraft-lon -85.9158 --agl 60 --heading 45 \
  --count 30 --rate 2
```

`inject` refuses to send if the target is outside that camera's field of view
from the state you gave it, or if the record would not survive the 512-byte cap,
the tap's framing or the server's `validate()`. Both refusals are results: the
first says that aircraft cannot see what the other one is reporting.

On the dashboard you should see one **Areas of interest** row per aircraft, each
with its own bearing and range, and on the rows that correlate, "also seen by …
N m apart". `span_m` is your live calibration check: if two aircraft looking at
one agreed point disagree by more than ~50 m, a mount angle is wrong.

### What live testing is still blocked on

- **All three aircraft were offline on 26 Oct** (Cruza last seen 11 min, quadpi
  9 min, tfwdrone intermittent). Nothing here has been run over the air.
- **quadpi is provisioned for `ebach` only** — our keys are not in its
  `authorized_keys`, so the dashboard cannot open its tap. Same blocker as the
  fleet dashboard and the 20 Oct flight review. Needs ebach.
- **`companion/deploy-observe.sh` still hardcodes `ebach`** as the service user;
  the Cruza's installed copy was fixed in place. Parameterising the owner is the
  proper fix.
- **No detector on quadpi or rn03.** Cross-cueing from a real camera on those
  two needs either an IMX500 or a CPU detector publishing the same record shape
  to the same loopback port. The record format and the whole path downstream are
  already proven, so that is a self-contained piece of work.
- **Mount angles in `swarm.SENSORS` are placeholders** (quadpi 30° down, rn03
  25° down) and must be measured before any field cross-cue is believed.
