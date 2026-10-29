# Mission handover: image + location from the Cruza, operator approve/deny — 27 Oct 2026

ebach's dashboard now has a **Mission handover** panel: each geolocated
observer cue waits there, with its image, for the operator to approve or deny
handing it to a live aircraft. This note records the message format the Cruza
would need to send for images, and what was verified.

**None of jbrascom's files are changed.** The dashboard side lives in files of
ebach's own: `handover.py`, `handover_intake.py`, `dist/handover.js`, plus
small hooks in `server.py`, `command-workflow.js`, `index.html` and
`fleet.css`. The Cruza side is only a proposal for him to review:
[proposals/cruza-image-chips](proposals/cruza-image-chips/README.md).
Without it, handover works with location only.

## What the Cruza would send (if jbrascom adopts the proposal)

Nothing about the existing detection record changes. Keep sending it exactly
as `companion/observe.py` does today, **including `seq`**:

```json
{"t": 1793150000.12, "seq": 93, "cls": "person", "score": 0.82,
 "az_rel_deg": -4.1, "el_rel_deg": 6.3, "fov": [66.0, 49.0],
 "bbox": [0.45, 0.4, 0.55, 0.6]}
```

**New: an image chip**, sent as numbered parts on the same loopback port
(15620). Each part is a separate datagram and must stay within the existing
512-byte cap, so **the deployed `observe-tap.py` and the dashboard reader do
not change** (no redeploy of the root-owned tap, no change to its sha256):

```json
{"t": 1793150000.12, "chip": 93, "part": 0, "parts": 9, "jpg": "<base64, ≤400 chars>"}
```

- `chip` is the `seq` of the detection record that the image shows. Send the
  detection first, then its parts.
- `parts` ≤ 64; each `jpg` ≤ 400 base64 characters, cut on 4-character
  boundaries so every part decodes on its own (400 is a multiple of 4).
- The joined bytes must be one complete JPEG (starts `FF D8 FF`, ends
  `FF D9`) of at most 24 KB. Anything else is discarded on the laptop.
- All parts must arrive within 15 s; the laptop keeps a finished chip for 120 s.
- Suggested chip: the detection box plus a margin, scaled to about 160×120,
  JPEG quality ~70: 3–10 KB, i.e. 10–35 datagrams. Send **one chip per new
  area of interest, and again at most every ~20 s while it stays in view or
  when the score improves**. Not one per frame. At that rate it costs well
  under 1 kB/s of the Cruza's LTE budget.
- Space the parts by a few milliseconds; the tap's receive buffer is 32 KB.

The chip has to come from the frame the detection ran on, which is one more
reason for **Option C** in `STATUS-swarm-observation-2026-10-27.md` (one
process owning the IMX500 and producing video, detections and chips). Until
that exists the Cruza can send video or detections, not both.

## What the dashboard does with it

- `handover_intake.py`: `Intake` stands in for the observation store at the
  readers' call site. It passes every detection to the unchanged store, takes
  chip parts into a `ChipAssembler` (validated and reassembled per aircraft,
  keyed by the reader's own aircraft name), and remembers which store entry
  each `seq` went to.
- `handover.py`: every geolocated cue seen within the last 2 s becomes a
  handover request. Same-class cues within 120 m merge into one request.
  Decided requests absorb later sightings for 5 minutes, so a denied target is
  not offered again straight away. Pending requests expire after 180 s without
  a sighting.
- **Approve** (quadpi or TFW drone) needs a position no older than 60 s. It
  records the decision and freezes the approved position. **Nothing is
  transmitted by approving.** If the aircraft's control link takes a point
  command, the dashboard prefills its command workflow (Fly to point & hold, or
  Loiter); the operator still sets the altitude, reviews and sends. Otherwise
  it is **decision only**: the point is marked ◎ on the map for the safety
  pilot and logged with `"mode": "decision-only"`. This is the mode for the
  28 Oct flight test, since quadpi's installed bridge takes arm/disarm only.
- **Deny** takes an optional reason (False detection / Not a priority / Unsafe
  or airspace / Duplicate).
- Every approval, denial and expiry is appended to `runtime/handover.log`
  (JSON lines), and the image that was looked at is saved to
  `runtime/handover/<time>-<id>.jpg`. Both are ignored by Git.
- State lives on the server, so every open page shows the same queue.
- The panel is hidden until a request exists. While one awaits a decision it
  moves above the map with an amber frame and scrolls into view for each new
  request (not while the command workflow has focus); once none is pending it
  returns under the map. A request whose position is over 60 s old shows
  "Approve: waiting for a fresh sighting" until the Cruza sees it again.

## Placement issue for the swarm code (needs the partner)

`swarm.picture()` places **every** cue still in the store using the reporting
aircraft's *current* heading and position. A cue last seen 9 s ago on a
turning Cruza is therefore re-projected with a heading that is now ~20–50°
different. In the bench run below, one stationary car became five areas of
interest whose estimated ranges ran from 550 to 832 m, and the areas-of-interest
panel still shows the same person at several bearings.

The handover queue works around it by only taking cues seen within 2 s.
The real fix is to place each cue **when its record arrives** (or with
telemetry matched to the record's `t`) and keep that position on the store
entry. Telemetry latency over DERP (350 ms–1 s) still applies on top of that.

## Bench verification (27 Oct, no aircraft)

A harness ran the real `server.Handler`, `ObservationStore`, `ChipAssembler`,
`swarm` and `HandoverQueue`. It used a fake Cruza on a 400 m orbit at 80 m and
~16 m/s, publishing detections and chips (every datagram checked against the
512-byte cap), and a fake "quadpi" link that reports itself live and in the air
but whose `execute()` sends nothing. Nothing touched SSH, MAVLink or any aircraft.

- A simulated person 700 m from the orbit centre produced **one** request with
  its image; its position was within ~5 m of truth when first offered and
  ~37 m at approval (range 606 m).
- Approve → the quadpi workflow was set to Fly to point & hold at the approved
  point, the altitude box focused, Review disabled until an altitude was
  entered. 30 m → Review → Send: the link received exactly
  `{"action": "goto", "latitude": 33.72335…, "longitude": -85.90937…, "altitude_m": 30}`.
- A simulated car was denied with "False detection"; later sightings were
  absorbed, not offered again. Both decisions were logged with their images.
- Tests: `test_handover.py`; all dashboard and swarm tests pass, plus the
  map and panel JS checks. The proposed `observe.py` patch was also run in
  `--synthetic` mode through the unmodified `observe-tap.py`: 36 frames, the
  largest 465 bytes, and four detections with valid images.

Decision-only, 27 Oct evening (same harness, no control link registered):
the card offered "quadpi · decision only"; Approve recorded the decision,
marked the point on the map and left the command workflow untouched (no
aircraft, no point). The log line carried `"mode": "decision-only"` and the
harness recorded zero command executions.

Real Cruza on the bench, 28 Oct evening (aircraft on the ground, laptop over
Tailscale/LTE): after the fixes in
[proposals/cruza-2026-10-28](proposals/cruza-2026-10-28/README.md), real IMX500
person detections became handover requests with real image chips (5–6 KB),
and approve (H4, to TFW drone) and deny (H3) were logged. Positions were
"estimated" because a camera on the ground gives no range.
On 29 Oct the corrected crop was checked: a person standing off to one side of
the frame came out centred in the card's picture.

Not yet verified: chips in flight, positions from a flying Cruza, a handover
sent over a real live link.
Before any real handover flight, re-confirm props and area before quadpi is armed.
