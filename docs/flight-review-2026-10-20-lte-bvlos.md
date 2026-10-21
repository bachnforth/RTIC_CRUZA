# Flight review 2026-10-20 — 3.8 km out-and-back, and what it says about the network architecture

Log 30 retrieved over USB (COM15, disarmed, read-only) into
`logs/2026-10-20/download-162053_202463/`: 37,584,896 bytes, SHA-256
`2c05e049…1137e7`. Fresh parameter snapshot in
`params/cruza_params_2026-10-20_162053_202463_postflight.params`.

**Headline:** the LTE/Headscale companion path worked as a real ground-control link for
the whole flight, including the 58 seconds when the 2.4 GHz RC link was completely dead at
3.6 km. The ELRS telemetry pipe, by contrast, was saturated for most of the flight. That
reverses the assumed roles: LTE is not yet a redundant path, it is currently the *only*
usable GCS path at range, and it has never been commissioned as one.

Everything below is measured from log 30 and from live read-only checks on this laptop.
No parameter was written and no setting was changed.

---

## 1. The flight

| | |
|---|---|
| Firmware | ArduPlane **4.7.2** (fb773567), TBS_LUCID_H7_WING_AIO |
| Armed / disarmed | t=542.8 → 1328.3 s (**19:34:56 → 19:48:01 UTC**, 14:34–14:48 CDT), **13 min 5 s** |
| Mission | 47 items; takeoff → 15 outbound WPs at 100 m → (re-upload) → items 44–46 → NAV_LAND |
| Max distance from launch | **3,775 m** at t=839 s |
| Altitude | 100 m commanded, **139.9 m peak** above home |
| Wind (EKF) | 2.5–3.8 m/s from ~350° |
| GPS | 18–27 sats, HDOP 0.51–0.72, no glitches |
| Health | **no ERR records, no EKF failsafe, no accel clipping, no logger drops** (DSF Dp=0) |
| CPU | loop 50 Hz, load 67–69 %, MaxT 20.0 ms, NLon=0, 599 kB free |

Sequence of events, from the log:

```
550.0  AUTO armed, mission item 1 Takeoff (target 60 m)
562.2  MODE -> RTL, reason 4 = BATTERY FAILSAFE   ("Battery 1 is low 21.55V")
587.5  MODE -> AUTO (GCS command); "Takeoff complete at 100.65m"
679.0  RC lost 2.8 s at 1,065 m
827.5  RC lost 1.2 s at 3,588 m
831.2  RC lost — stays lost for 58.2 s
835.9  MODE -> RTL, reason 3 = RADIO FAILSAFE, at 3,649 m
889.5  RC restored, inbound, at 2,618 m
901.8  "Flight mode RTL restored"
1047.6 MODE -> LOITER (GCS)
1084.3 "Flight plan received / New mission"   <- arrived over the companion UART
1144.0 "Flight plan received / New mission"   <- again
1249.9 DO_SET_MISSION_CURRENT = 44 (GCS)
1258.5 MODE -> AUTO, items 44 (40 m) -> 45 (20 m) -> 46 Land
1303.1 Flare 3.7 m, sink 1.91 m/s, speed 14.0 m/s
1308.7 touchdown
1328.3 disarmed, 24.22 m from the LAND point
```

---

## 2. What the flight proves about the companion / LTE path

The flight controller's own UART and MAVLink counters are the evidence here. Channel map
on this airframe (five MAVLink-enabled ports, so `MAVn_` groups map in port order):

| MAVLink chan | Port | Role | Measured, armed window |
|---|---|---|---|
| 0 | SERIAL0 | USB | not connected; `tf` (times-buffer-full) climbing, 0 pkt/s |
| 1 | **SERIAL2 @115k** | **Pi companion** | **Tx 3,341 B/s ≈ 98 pkt/s; Rx 36 B/s; rxdp 0** |
| 2 | SERIAL4 @460k | ELRS (RC + MAVLink) | Tx **630 B/s median**, Rx 6,412 B/s, **stream slowdown pinned at 2,000 ms** |
| 3 | SERIAL8 @57k | **nothing attached** | Tx 3,289 B/s, Rx 0 — see §6.2 |
| 4 | SERIAL9 | second USB CDC | not connected, blocked |

Three results follow, and they are the practical answer to "will this work in the network
architecture":

**2.1 The companion link carried a live, bidirectional GCS for the entire flight.**
Inbound traffic on SERIAL2 is a steady 21 B/s — exactly one 21-byte MAVLink 2 heartbeat
per second — and chan1's receive counter incremented at 1.0–2.9 /s continuously from
t=543.6 (QGC attached, one second before arming) to disarm. The only inbound gap longer
than 3 s in the whole log is *before* that, 327→543 s. Six of 816 UART samples show zero
inbound bytes. **In 785 s of flight the uplink never went quiet for more than about a
second.** Commands logged as arriving from sysid 255 / comp 190 (QGC): arm, five mode
changes, `DO_SET_MISSION_CURRENT`, disarm.

**2.2 Both 47-item mission uploads came in over the companion link, not over ELRS.**
SERIAL2's inbound rate jumps from 21 B/s to 184–462 B/s at t=1078.9–1084.9 and again at
t=1138.9–1143.9, ending exactly at the two "Flight plan received" messages; SERIAL2's
outbound stream drops to 435–1,449 B/s during those bursts as the uploads take priority.
The ELRS port shows no corresponding inbound change. **A full mission transfer over the
cellular path, in the air, at ~40 m from home — that is the mission-upload test the
companion README still lists as "Not verified".**

**2.3 It stayed up through the RC blackout.** During 831–890 s — RC RSSI exactly 0,
radio failsafe, aircraft in RTL at 3.6 km — SERIAL2 continued at 3,357 B/s out and 21 B/s
in, chan1 at 98.2 pkt/s with zero dropped packets. The cellular path was the only thing
still connecting the operator to the aircraft for that minute.

**What this does *not* prove.** The FC can only see its own UART. It proves a GCS was
reaching the FC through the Pi and that the FC's telemetry was leaving. It does **not**
identify the transport (LTE vs. any Wi-Fi the Pi may still have had), does not show
whether the tailnet path was direct or DERP-relayed, does not measure RTT or modem
signal, and says nothing about video. All of that lives in the Pi-side logs, and the Pi
(`tfwcruza`, 100.100.0.58) went offline on the tailnet at 20:10 UTC — 22 minutes after
landing — so none of it has been retrieved. At 3.8 km from the operator, LTE is the only
transport that could plausibly have carried it, but that is inference, not evidence.

**Retrieve the Pi-side session files before anything else.** `path-health.py` keeps
4 MiB segments to a 128 MiB cap and deletes oldest-first on every sample, so the flight
window will age out. Then:

```bash
python3 /opt/cruza-path-health/path-health.py --report <each session segment>.jsonl
```

---

## 3. Practicality in the fleet network architecture

The target architecture is the one in `rekon-mesh/RN03/fleet-transport-design.md`:

```
Cruza -- LTE -- Headscale -- ground gateway (alien03) -- 915 MHz Doodle mesh -- RN03 / QuadPi
```

Live state of that chain, checked read-only from this laptop today:

| Hop | State | Evidence |
|---|---|---|
| Cruza → tailnet | **works** | `tfwcruza` 100.100.0.58, `tag:team1`, last seen 20:10 UTC |
| Gateway readiness | **now complete** | `gcs/check-gateway.ps1`: mesh address, **IP forwarding Enabled on Wi-Fi 3 and Tailscale**, `IPEnableRouter=1` persistent, service running, `PrimaryRoutes = 10.223.0.0/16`, inbound ICMPv4 allowed — 6/6 |
| Route auto-approval | **in policy** | `headscale-policy-NEW-20261015.hujson` autoApprovers `10.223.0.0/16` → `tag:team1`; live `Self.PrimaryRoutes` confirms approved+active |
| Cruza accepts the route | **open** | `tailscale set --accept-routes` still not applied (ebach's) — ladder step 3 cannot pass without it |
| Gateway → mesh | **down today** | `10.223.196.103` and `10.223.53.30` both unreachable; the handheld/Pi were not on the air |
| Cruza → mesh peer app traffic | **blocked by design** | `companion/cruza.py` `tail_ip()` rejects anything outside `100.64.0.0/10`, and `android_ip` is a scalar — one peer, tailnet-only |
| alien08 as an alternative gateway | **still advertises nothing** | peer AllowedIPs = `100.100.0.23/32` only |

So: the gateway-side gap that blocked ladder step 3 since 15 Oct **is closed** — that is
new and worth telling the team. Two things still stand between today's result and the
hybrid architecture, and neither is a networking problem:

1. **`--accept-routes` on the Cruza.** One command, ebach's aircraft. Until then the
   Cruza receives `10.223.0.0/16` and ignores it.
2. **The companion software cannot address the mesh.** Even with the route accepted,
   `cruza.py` will refuse a `10.223.x` endpoint for MAVLink, video or the firewall rule.
   That needs the endpoint-list change already identified in
   `docs/mesh-hybrid-handover-2026-10-14.md` Finding 1 — per-entry address, port and
   video flag, with `multiudpsink` for fan-out behind the single hardware encode. Do not
   loosen `tail_ip()`; add a second validator, as that note says.

Also unchanged: the gateway is **Windows**, so there is no SNAT. Every mesh-side device
that must answer the Cruza needs `100.64.0.0/10 via 10.223.53.10`. Only RN03's Pi has it
today. That is the per-aircraft item the design doc warns gets forgotten in the field,
and it is an argument for moving the gateway onto the Linux Pi as planned.

### Bandwidth and data budget — now measured, not estimated

| Flow | Measured | Per hour |
|---|---|---|
| FC → Pi telemetry (default `MAV2_` rates, 10 Hz EXTRA1/2) | 3,341 B/s | **12.0 MB/h** at the UART |
| Same with UDP/IP/WireGuard overhead | — | ~16–19 MB/h |
| GCS → FC | 36 B/s | ~0.1 MB/h |
| Video, 400 kbps profile (not run this flight) | — | 180 MB/h |

On the 24 GB/year SIM that is roughly **120 flight hours/year with video, ~1,200 without**
— telemetry is not the constraint on LTE. On the mesh it would be: 3.3 kB/s of telemetry
against ~1.53 Mbps of shared 10 MHz airtime is affordable, but the RN03 precedent cut its
companion port to **1 Hz** deliberately, and this port is still at ArduPilot defaults. If
the same FC port is ever asked to feed the mesh, trim `MAV2_*` first.

---

## 4. The `path-health` logger: what it will and will not tell you

Read from `quadpi-path-health-handover-2026-10-20` (`path-health.py`, `comms-health.py`,
`flight-health.py`). The design is careful and the bounded-evidence discipline is right —
fixed key sets, no payloads or positions, explicit limits strings, per-boot sessions,
`CAP_NET_RAW` only, `MemoryMax=64M`, `Nice=10`. Four findings matter for how it will
actually serve this architecture.

**4.1 It structurally cannot measure the hop that has never passed.** `validate()`
requires `source_ip` and `peer_ip` to both sit inside the declared `network`
(`path-health.py:34-40`), and `probe()` requires `ip route get PEER from SOURCE` to come
back on the *same interface* that holds `source_ip` (`:61-73`). That is exactly the right
guard for a mesh hop, where both ends are on one flat L2. It cannot express a *routed*
hop. The Cruza has no `10.223.x` address, so a Cruza→`10.223.53.10` target can only ever
report `unavailable / source_address_absent`. **Ladder step 3 — the hop the whole design
turns on — is outside this logger's model.** Measuring it needs a second target type:
probe a peer outside the source's network and assert the egress interface is `tailscale0`
rather than asserting same-interface.

**4.2 As installed on the Cruza it watches the wrong gateway.** The package's own
verification note records the Cruza probing **100.100.0.23** (alien08) over `tailscale0`
at 125 ms. alien08 advertises no routes — confirmed again today — and the approved
subnet route is on alien03 / 100.100.0.29. So the Cruza's evidence file answers ladder
step 2 (tailnet reachability) against a node that cannot be the doorway. Same root cause
as the `10.223.58.11` phone-slot error already sent back in
`rekon-mesh/RN03/HANDBACK-path-health-20261020.md` §1a. Confirm
`/etc/cruza-path-health.json` on the Pi and repoint it at **100.100.0.29**.

**4.3 Its passive traffic classifier will see almost nothing on the Cruza.** The
`Observer` only counts packets where `(src,dst)` is exactly `(source_ip, peer_ip)` or the
reverse (`:119-121`). The Cruza's operational flows go to the **Android phone**
(100.100.0.57) — MAVLink 14560 and video 5600 — not to the gateway. On RN03 this
classifier was the best part of the return evidence, because there the probe peer *is*
the traffic peer. On the Cruza, with the gateway as peer, `traffic` will stay near-empty
while 3.3 kB/s of real telemetry crosses the same interface. The flows it would classify
(`telemetry` 14550/14560, `video` 5600) are already in the code — they just need the
phone as a second target, or `comms-health.py`, whose `Observer` *is* written around the
phone and whose main loop is deliberately not started.

**4.4 Smaller things, in descending order of likely bite:**

- **Silent stop under storage pressure.** `RotatingLog.write()` returns `False` and drops
  the sample when free space is under the 256 MiB reserve (`comms-health.py:105`), logging
  only a journal line. The Cruza also writes 5-minute video segments; the logger goes
  quiet exactly when the card fills, and `skipped_for_low_disk` only reaches the file on a
  *successful* write.
- **Shared filename glob.** `path-health` writes through `comms.RotatingLog`, so its files
  are also `comms-*.jsonl`, and retention unlinks any matching file over the cap
  (`:119-126`). Two loggers pointed at one `--output-root` would delete each other's
  segments. Different roots today; one flag away from not being.
- **A subprocess per second.** The observer thread calls `interface_for()` on every socket
  timeout (`path-health.py:109`), i.e. `ip -j -4 address` roughly 1×/s, on top of ~5
  subprocesses per 10 s sample. On a Zero 2 W already encoding video it is small but
  avoidable — cache the interface and re-resolve on error.
- **`ReadWritePaths` on a missing directory** fails unit startup under
  `ProtectHome=read-only` unless the installer has created it. Fine here; it is the next
  thing to bite on QuadPi, along with the hard-coded `ebach` already reported.
- The `--report` output is honest about what it is not (hop reachability, not delivery),
  and 10 s sampling means sub-10 s outages are invisible. Both are stated in the code's
  own limits strings. Keep that language when quoting results upward.

**Verdict on the logger:** keep it, fix the target, add the phone, and treat it as
*aircraft-side hop evidence only*. It will not, as configured, produce the evidence this
architecture actually needs — a Cruza→mesh-address probe and a record of the operational
flows. Gateway-side logging is still uncommissioned, so there is no counter at the far end
to pair with any of it.

---

## 5. Flight issues, worst first

**5.1 Battery failsafe fired 12 s after takeoff and put the aircraft in RTL mid-climb.**
Pack at arm 24.83 V (6S, 4.14 V/cell). Under takeoff throttle it sagged to **21.46 V** —
below `BATT_LOW_VOLT = 21.6` — and with `BATT_LOW_TIMER = 10` the failsafe tripped at
t=562.2 and `BATT_FS_LOW_ACT = 1` took RTL. Voltage recovered to 23.9 V as soon as
throttle came back, and the rest of the flight sat at 22.3–23.5 V, landing at 22.71 V.
The pack was never actually low; the threshold is set above this airframe's full-throttle
sag. It cost an interrupted takeoff and a mode fight at low altitude, and it is the single
most likely event to repeat. Related: `BATT_ARM_VOLT = 23.0` then blocked re-arming
("PreArm: Battery 1 below minimum arming voltage") at 22.71 V.

**5.2 The current monitor is still invalid** — 0.187–0.213 A for the entire flight, 73.5
mAh total, `RemPct` stuck at 97–99 %, and `Res` wandering to 24 Ω, which in turn makes the
`VoltR` resting estimate (up to 29.98 V on a 6S pack) meaningless. So every battery
decision is voltage-only, with no sag compensation available. This has been open since
2026-10-09.

**5.3 RC link limit at ~3.6 km.** Three dropouts: 2.8 s at 1,065 m, 1.2 s at 3,588 m, then
**58.2 s starting at 3,649 m** — which began within 1.5 s of reaching the farthest
waypoint. Link returned at 2,618 m inbound. Failsafe behaved exactly as configured
(`FS_SHORT_ACTN=0`, `FS_LONG_ACTN=1` → RTL after 5 s) and RTL brought it home. Note the
reported RSSI either side stayed high (RemRSSI 74–98) right up to the drop, so this looks
like a hard range/link-budget cliff rather than a gradual fade — and the 1.1 km dropout
says the margin is not clean even close in.

**5.4 The ELRS MAVLink pipe was saturated for most of the flight.** `RADIO_STATUS` txbuf
sat at **0** from t≈700 onward, ArduPilot's stream slowdown on that channel was pinned at
its **2,000 ms** maximum, and FC telemetry out fell to 42–177 B/s at times (630 B/s
median) while the receiver pushed **190 pkt/s / 6.4 kB/s inbound**. QGC over ELRS in this
configuration is not a working GCS path — it is a trickle competing with RC for the same
airtime. If ELRS is meant to be the backup link, its `MAVn_` rates (chan 2 = `MAV3_*`,
still at 10 Hz defaults) need cutting hard, the way RN03's companion port was cut to 1 Hz.

**5.5 Re-engaging AUTO at item 44 produced a 70° roll-demand step.** At t=1258.6 nav
demanded −44.2° while the aircraft was rolled +26° out of the LOITER circle; same again at
1275.5 (−44.3° vs +7.5°), during the descent through 40 m. The airframe caught up in about
0.3 s and there is no ERR or EKF complaint, but stepping from a loiter into a hard
opposite turn at 40 m on final approach is worth avoiding — set the resume waypoint while
still at pattern altitude, or insert a lead-in leg.

**5.6 Two mission re-uploads in flight, and a mode sequence that needed five commands.**
AUTO → RTL(batt) → AUTO → RTL(radio) → LOITER → RTL → LOITER → AUTO. It worked, and it
shows the LTE link was genuinely steerable, but a 47-item plan uploaded twice mid-air with
`DO_SET_MISSION_CURRENT` to resume is a procedure that wants writing down before the next
one, not improvising.

**5.7 Housekeeping that is now flying:**

- `FENCE_ENABLE = 0` on a 3.8 km BVLOS-style sortie. The stored fence (300 m radius,
  100 m ceiling) would have fought the mission, so this was presumably deliberate — but it
  means there was no geofence at all. A real fence sized to the route is cheap insurance.
- Peak altitude **139.9 m above home** against a 100 m commanded cruise. 139.9 m is above
  400 ft AGL; worth a deliberate decision rather than a by-product of the outbound climb.
- `ARMING_MAGTHRESH = 300` (default 100) and `ARMING_SKIPCHK = 4096` are still in place
  from the October bench work.
- `SERIAL7` is configured for ESC telemetry (protocol 16) and received **zero bytes** all
  flight — either not wired or not enabled at the ESC.
- `FS_GCS_ENABL = 0`, so losing the LTE GCS does nothing. Correct for now, and it is the
  reason 2.3 was survivable; it becomes a real decision the moment LTE is treated as the
  primary control path.

**5.8 Good news, stated plainly:** the airspeed integration is working. `ARSPD_USE = 1`,
`ARSPD_AUTOCAL = 0`, `ARSPD_RATIO = 1.6745`, sensor healthy for all 8,144 samples. The
wind triangle closes: outbound into a 3 m/s northerly, airspeed 20.0 / groundspeed 18.1;
inbound, airspeed 20.8 / groundspeed 24.6 — both within ~0.5 m/s of the EKF wind estimate,
so the ratio is corroborated in flight to within a few percent despite differing from the
1.85 recommended in `docs/airspeed-integration-summary.md`. Landing was clean: flare at
3.7 m, 1.91 m/s sink, touchdown vibration peak 33.8 m/s² with **zero clips**, stop 24.2 m
from the LAND point. Attitude tracking in flight was good; no ERR, no EKF failsafe, no log
drops, 67 % CPU.

---

## 6. Undocumented changes found in the snapshot

Six flights and ~40 minutes of flight time happened between the 13 Oct review and today
(`STAT_FLTCNT` 9→15, `STAT_FLTTIME` 1462→3851 s, `STAT_BOOTCNT` 140→193, `STAT_DISTFLWN`
22.2→68.9 km) with nothing in the repo. Changes since
`cruza_params_2026-10-13_124918_639183`:

**6.1 Changes that are clearly intentional and should be written up:**

| Parameter | 13 Oct | Now | Note |
|---|---|---|---|
| Firmware | 4.7.1 | **4.7.2** | |
| `BATT_ARM/LOW/CRT_VOLT` | 13.2 / 14.0 / 13.2 | **23.0 / 21.6 / 21.0** | **moved to a 6S pack** |
| `BATT_CAPACITY` | 4000 | 3000 | |
| `AIRSPEED_CRUISE` | 15 | **20** | |
| `ARSPD_USE` / `AUTOCAL` / `RATIO` | 0 / 1 / 1.817 | **1 / 0 / 1.6745** | speed control now live |
| `MIS_TOTAL` | 11 | **47** | |
| Accel, compass, AHRS trims | — | all re-calibrated | |

**6.2 One change that needs explaining before the next flight:**
`AHRS_ORIENTATION` is back to **0**. It was set to **6 (Yaw270)** on 2026-10-08 as the fix
for the nose-dive launch, and `docs/status.md` still records 6 as current. Orientation 0
plus a full re-calibration is consistent with the AIO having been physically remounted —
and the flight flew well, which is the strongest evidence it is right — but the repo and
the aircraft now disagree about a parameter that caused a crash. Confirm which it is and
correct `status.md`.

**6.3 `SERIAL8_PROTOCOL = 2` (MAVLink 2, 57600) with nothing attached.** This port
streamed **3,289 B/s — 57 % of its line capacity, ~96 MAVLink packets/s — into an
unconnected UART for the entire flight**, at default `MAV4_*` 10 Hz rates. It is pure
waste: FC CPU, a serial DMA channel and about 2.6 MB of generated telemetry per flight for
no listener. (`SERIAL9_PROTOCOL = 2` is the second USB CDC and was correctly blocked, so it
costs nothing.) Either something is supposed to be on SERIAL8 and is not wired, or set
`SERIAL8_PROTOCOL = -1`.

---

## 7. Recommended order of work — nothing applied

1. **Pull the Pi-side logger sessions off `tfwcruza`** before retention eats the flight
   window, and run `--report` per session. Without them none of §2 can be attributed to
   LTE rather than Wi-Fi, and there is no RTT, DERP/direct, modem-signal or video record
   of the flight at all.
2. **Battery thresholds.** Set `BATT_LOW_VOLT` / `BATT_CRT_VOLT` / `BATT_ARM_VOLT` from a
   measured full-throttle sag on this 6S pack, not from cell-count arithmetic. Until the
   current monitor is fixed there is no mAh fallback and no sag compensation.
3. **Fix the current monitor** (§5.2) — it blocks every energy and endurance question.
4. **`SERIAL8_PROTOCOL = -1`** unless something is meant to be there (§6.3).
5. **Repoint the Cruza's path-health target to 100.100.0.29**, and add the phone
   (100.100.0.57) as a second target so the passive classifier sees the real flows (§4.2,
   §4.3).
6. **`tailscale set --accept-routes` on the Cruza**, then run ladder step 3 against
   `10.223.53.10` with the gateway up — the gateway side is now 6/6 and this is the first
   time step 3 can actually be attempted (§3).
7. **Decide the ELRS role.** If it is the backup control link, cut `MAV3_*` stream rates
   so telemetry stops competing with RC; if it is RC-only, consider dropping MAVLink on
   SERIAL4 entirely and letting the LTE path own telemetry (§5.4).
8. **Range.** 3.6 km is this RC link's demonstrated cliff. Either plan inside ~2.5 km,
   improve the TX/antenna arrangement, or accept RTL-on-failsafe as the operating mode for
   the far end of the route — which is what happened today, and it worked.
9. **Fence and altitude** sized to the actual route, as a deliberate decision (§5.7).
10. **Write the procedure** for mid-flight mission change: upload at pattern altitude,
    `DO_SET_MISSION_CURRENT`, then AUTO — with a lead-in leg so AUTO re-entry does not
    demand a 70° roll reversal on descent (§5.5, §5.6).

## 8. Not verified / out of scope

- Nothing on the Pi was inspected live; it was offline from 20:10 UTC. All companion-side
  statements come from the FC's UART counters or from the package source and its README.
- No video evidence exists for this flight from either end.
- Mesh reachability could not be checked end-to-end: the ground handheld and RN03's Pi
  were both unreachable from the gateway today.
- Hop reachability is not authenticated application delivery; observation forwarding
  remains disabled as shipped. Gateway-side persistent logging is not commissioned.
- No parameter was written, no mission uploaded, no FC command sent during this review.
