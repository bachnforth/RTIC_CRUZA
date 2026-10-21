# Handover: the LTE path flew as a real GCS link — and it is now load-bearing

From: jbrascom (RN03 / alien03, the gateway)
Date: 20 Oct 2026
Re: Cruza log 30, and what it changes for `quadpi-path-health-handover-2026-10-20`

**Bottom line.** Today's 13-minute, 3.8 km out-and-back proves the LTE/Headscale companion
path works as a ground-control link: continuous 1 Hz GCS heartbeat from arm to disarm, two
full 47-item mission uploads *in the air*, five mode commands — and it stayed up through
the 58 seconds when the 2.4 GHz RC link was completely dead at 3.6 km. Over the same
flight the ELRS MAVLink pipe was saturated and nearly useless for telemetry. That inverts
the assumption in all our notes: **LTE is not a second, independent path any more. It is
currently the only usable GCS path at range, and it has never been commissioned as one.**

The evidence for all of that is the flight controller's own counters. The Pi-side evidence
— which is the half that would attribute it to LTE rather than Wi-Fi, and the only half
that knows anything about RTT, DERP, modem signal or video — **was never retrieved, and
the Pi went offline 22 minutes after landing.** That is the first ask below.

Full analysis: [`docs/flight-review-2026-10-20-lte-bvlos.md`](flight-review-2026-10-20-lte-bvlos.md).

---

## 1. What was retrieved, and where it is

Read-only USB pull from the FC while disarmed (COM15). No parameter written, no mission
uploaded, no FC command sent.

| Artifact | Path |
|---|---|
| DataFlash log 30 | `logs/2026-10-20/download-162053_202463/log_00030.BIN` — 37,584,896 bytes, SHA-256 `2c05e049b0900287b4192140c62761927e81bc6394f9fa8e84528967941137e7` |
| Summary / plot / records | `log_00030.summary.json`, `log_00030.png`, `log_00030.records.json` |
| Full parameter snapshot | `params/cruza_params_2026-10-20_162053_202463_postflight.params` (1256/1256 indexes) |
| Onboard log index | `logs/2026-10-20/download-162053_202463/log-index.json` |

Flight: armed t=542.8 → disarmed t=1328.3, i.e. **19:34:56 → 19:48:01 UTC** (14:34–14:48
CDT), 13 min 5 s. ArduPlane **4.7.2**. Max 3,775 m from launch at t=839 s, 100 m commanded
cruise with a 139.9 m peak, wind 2.5–3.8 m/s from ~350°. No ERR records, no EKF failsafe,
no accelerometer clipping, no logger drops, 67 % CPU.

## 2. What the FC measured on each link

Five MAVLink-enabled ports on this airframe, so the `MAVn_` groups map in port order:

| chan | Port | Role | Armed window |
|---|---|---|---|
| 0 | SERIAL0 | USB | not connected, blocked |
| 1 | **SERIAL2 @115k** | **Pi companion** | **Tx 3,341 B/s ≈ 98 pkt/s, Rx 36 B/s, 0 dropped** |
| 2 | SERIAL4 @460k | ELRS (RC + MAVLink) | Tx **630 B/s median**, Rx 6,412 B/s, stream slowdown pinned at **2,000 ms** |
| 3 | SERIAL8 @57k | **nothing attached** | Tx 3,289 B/s into an unconnected UART |
| 4 | SERIAL9 | 2nd USB CDC | not connected, blocked |

Three results:

- **Uplink never went quiet.** SERIAL2 inbound sits at a steady 21 B/s — exactly one
  MAVLink 2 heartbeat per second. chan1's receive counter incremented 1.0–2.9 /s
  continuously from t=543.6 (QGC attached, one second before arming) to disarm. Six of 816
  UART samples show zero inbound bytes; the only >3 s inbound gap in the log is *before*
  that window. Commands logged from sysid 255 / comp 190: arm, five mode changes,
  `DO_SET_MISSION_CURRENT`, disarm.
- **Both mission uploads came over the companion link, not ELRS.** SERIAL2 inbound jumps
  21 → 184–462 B/s at t=1078.9–1084.9 and again at 1138.9–1143.9, ending exactly at the
  two "Flight plan received" messages, while its outbound stream drops to 435–1,449 B/s as
  the transfer takes priority. The ELRS port shows no corresponding change. **That is the
  in-flight mission transfer the companion README still lists as "Not verified."**
- **It carried the RC blackout.** During 831–890 s — RC RSSI exactly 0, radio failsafe,
  RTL at 3.6 km — SERIAL2 ran 3,357 B/s out and 21 B/s in at 98.2 pkt/s with zero drops.

Measured data budget: **12.0 MB/h** of telemetry at the UART (~16–19 MB/h with UDP/IP/
WireGuard overhead), 0.1 MB/h up. With the 400 kbps video profile that is ~200 MB/h, so
roughly **120 flight hours/year** on the 24 GB SIM. Telemetry is not the constraint on
LTE — but these are ArduPilot default rates (`MAV2_EXTRA1/EXTRA2` at 10 Hz), 10× what RN03
budgets for its companion port. If this port is ever asked to feed the 10 MHz mesh, trim
`MAV2_*` first.

**What this does not prove, and please do not let it be quoted as proving:** the FC can
only see its own UART. It shows *a* GCS reaching the FC through the Pi and telemetry
leaving. It does not identify the transport, does not show direct vs DERP-relayed, gives
no RTT or modem signal, and says nothing about video. At 3.8 km from the operator LTE is
the only transport that could plausibly have carried it — that is inference, not evidence.

## 3. Urgent: retrieve the Pi-side logger sessions

`cruza-path-health` was running on the Cruza through the flight. Its output is the missing
half of §2, and `RotatingLog` deletes oldest-first on **every** sample (4 MiB segments,
128 MiB cap), so the flight window ages out on its own.

```bash
ls -lt /home/ebach/cruza-path-health/
# copy the segments covering 19:30-19:50 UTC off the Pi, then:
python3 /opt/cruza-path-health/path-health.py --report <each relevant segment>.jsonl
```

Also worth capturing while you are there, because none of it is recoverable later:
`journalctl -u cruza-router -u cruza-video --since "2026-10-20 19:25" --until "2026-10-20 20:15"`,
`sudo python3 /opt/cruza/cruza.py usage`, and whether `wlan0` was up at any point during
the flight (that is what settles LTE vs Wi-Fi).

## 4. Two things about the logger package you will want to know

Neither is a defect in the code — the bounded-evidence discipline in it is right, and the
limits strings are honest. Both are about what it can be *asked*.

**4.1 It structurally cannot measure ladder step 3.** `validate()` requires `source_ip`
and `peer_ip` to both sit in the declared `network` (`path-health.py:34-40`), and
`probe()` requires `ip route get PEER from SOURCE` to return the same interface that holds
`source_ip` (`:61-73`). That is exactly right for a mesh hop, where both ends share one
flat L2. It cannot express a **routed** hop. The Cruza has no `10.223.x` address, so a
Cruza→`10.223.53.10` target can only ever report `unavailable / source_address_absent` —
and that is the hop the whole fleet design turns on. Measuring it needs a second target
type: probe a peer *outside* the source's network and assert egress on `tailscale0`
instead of asserting same-interface.

**4.2 As installed on the Cruza it watches the wrong gateway, and sees none of the real
traffic.** Your own verification note records the Cruza probing **100.100.0.23** (alien08)
over `tailscale0` at 125 ms. alien08 advertises no subnet routes — I re-confirmed that
today, its peer AllowedIPs is `100.100.0.23/32` and nothing else — and the approved route
lives on alien03 / **100.100.0.29**. Same root cause as the `10.223.58.11` phone-slot
error in `rekon-mesh/RN03/HANDBACK-path-health-20261020.md` §1a. Separately, the
`Observer` only counts packets where `(src,dst)` is exactly source↔peer (`:119-121`), so
with the gateway as peer it will stay near-empty while 3.3 kB/s of real telemetry crosses
the same interface. The flows it would classify (`telemetry` 14550/14560, `video` 5600)
are already in the code — they just need the **phone (100.100.0.57)** as a second target.

Three smaller ones, in descending order of likely bite: it stops silently under storage
pressure (`write()` returns `False` below the 256 MiB reserve and only logs a journal
line, and the Cruza also writes 5-minute video segments); its files are `comms-*.jsonl`,
the same glob `comms-health` uses, so two loggers sharing one `--output-root` would delete
each other's segments; and the observer thread shells out `ip -j -4 address` roughly once
a second on a Zero 2 W that is also encoding video (`:109` — cache it, re-resolve on
error).

## 5. Where the fleet chain actually stands

Checked read-only from the gateway today.

| Hop | State |
|---|---|
| Cruza → tailnet | **works** — `tfwcruza` 100.100.0.58, `tag:team1`, last seen 20:10 UTC |
| Gateway readiness | **now 6/6** — `gcs/check-gateway.ps1`: mesh address, IP forwarding Enabled on Wi-Fi 3 *and* Tailscale, `IPEnableRouter=1` persistent, service running, `PrimaryRoutes = 10.223.0.0/16`, inbound ICMPv4 allowed |
| Route approval | **approved and active**, and `autoApprovers` for `10.223.0.0/16` → `tag:team1` is now in policy, so a re-advertise will not silently revert it |
| Cruza accepts the route | **open — yours**: `tailscale set --accept-routes` |
| Gateway → mesh | **down today**: `10.223.196.103` and `10.223.53.30` both unreachable, nothing on the air |
| Cruza → mesh app traffic | **blocked by design**: `cruza.py` `tail_ip()` rejects anything outside `100.64.0.0/10`, and `android_ip` is a scalar — one peer, tailnet only |

So the gateway-side gap that has blocked ladder step 3 since 15 Oct **is closed**. Step 3
is attemptable for the first time; it needs your `--accept-routes` and both radios up. Two
standing caveats: the gateway is still Windows, so there is no SNAT and every mesh-side
device that must answer the Cruza needs `100.64.0.0/10 via 10.223.53.10` (only RN03's Pi
has it) — and even with the route accepted, `cruza.py` cannot be pointed at a `10.223.x`
endpoint for MAVLink, video or the firewall rule. That is the endpoint-list change in
`docs/mesh-hybrid-handover-2026-10-14.md` Finding 1: per-entry address, port and video
flag, `multiudpsink` for fan-out behind the single hardware encode. Please do not loosen
`tail_ip()` — add a second validator.

## 6. Flight issues, worst first

1. **Battery failsafe RTL 12 s after takeoff.** Pack at arm 24.83 V; under takeoff throttle
   it sagged to **21.46 V**, below `BATT_LOW_VOLT = 21.6`, and with `BATT_LOW_TIMER = 10`
   the failsafe took RTL at t=562 mid-climb. It then needed a manual AUTO re-command. The
   pack was never low — 22.3–23.5 V for the rest of the flight, 22.71 V at landing — the
   threshold is simply set above this airframe's full-throttle sag. `BATT_ARM_VOLT = 23.0`
   then blocked re-arming afterwards. **Set these three from a measured sag on this 6S
   pack, not from cell-count arithmetic.** Most likely event to repeat.
2. **Current monitor still invalid** — 0.187–0.213 A for the whole flight, 73.5 mAh total,
   `RemPct` stuck at 97–99 %, and `Res` wandering to 24 Ω, which makes the resting-voltage
   estimate read 29.98 V on a 6S pack. So every battery decision is voltage-only with no
   sag compensation. Open since 9 Oct; it blocks every endurance question.
3. **RC cliff at ~3.6 km.** Three dropouts: 2.8 s at 1,065 m, 1.2 s at 3,588 m, then
   **58.2 s beginning at 3,649 m**, within 1.5 s of reaching the farthest waypoint. Link
   returned at 2,618 m inbound. Failsafe behaved exactly as configured and RTL brought it
   home. Reported RSSI stayed high right up to each drop (RemRSSI 74–98), so this reads as
   a link-budget cliff rather than a fade — and the 1.1 km dropout says the margin is not
   clean even close in.
4. **The ELRS MAVLink pipe was saturated** from t≈700 onward: `RADIO_STATUS` txbuf at
   **0**, ArduPilot's stream slowdown pinned at its 2,000 ms maximum, FC telemetry out
   down to 42–177 B/s at times while the receiver pushed 190 pkt/s / 6.4 kB/s inbound.
   Decide the role: if ELRS is the backup control link, cut `MAV3_*` rates hard so
   telemetry stops competing with RC; if it is RC-only, consider dropping MAVLink on
   SERIAL4 and letting the LTE path own telemetry.
5. **Re-engaging AUTO at item 44 produced a 70° roll-demand step** (−44.2° demanded against
   +26° actual at t=1258.6, and again −44.3° vs +7.5° at 1275.5 descending through 40 m).
   Caught up in ~0.3 s, no ERR — but stepping out of a loiter into a hard opposite turn at
   40 m on final is worth designing out with a lead-in leg.
6. **Housekeeping now flying:** `FENCE_ENABLE = 0` on a 3.8 km sortie; 139.9 m peak against
   100 m commanded (above 400 ft AGL); `ARMING_MAGTHRESH = 300` and
   `ARMING_SKIPCHK = 4096` still set from the October bench work; SERIAL7 configured for
   ESC telemetry and receiving **zero bytes**; `SERIAL8_PROTOCOL = 2` streaming 3.3 kB/s
   (57 % of its line rate, ~96 pkt/s) into an unconnected UART all flight — set it to `-1`
   unless something is meant to be there; `FS_GCS_ENABL = 0`, which is why item 3 was
   survivable and which becomes a real decision the moment LTE is treated as primary.

**Working well, stated plainly:** airspeed is integrated and corroborated — `ARSPD_USE=1`,
`AUTOCAL=0`, `RATIO=1.6745`, sensor healthy for all 8,144 samples, and the wind triangle
closes to ~0.5 m/s on both legs (outbound AS 20.0 / GS 18.1 into a 3 m/s northerly;
inbound AS 20.8 / GS 24.6). Note that differs from the 1.85 recommended in
`docs/airspeed-integration-summary.md`; the in-flight check supports the value now loaded.
Landing was clean: flare 3.7 m, 1.91 m/s sink, touchdown vibration peak 33.8 m/s² with
**zero clips**, stop 24.2 m from the LAND point. GPS 18–27 sats, HDOP 0.51–0.72.

## 7. Six flights happened with no record

`STAT_FLTCNT` 9→15, `STAT_FLTTIME` 1462→3851 s, `STAT_BOOTCNT` 140→193, `STAT_DISTFLWN`
22.2→68.9 km since the 13 Oct review, and nothing in the repo. Changes found in the
snapshot: firmware 4.7.1→**4.7.2**; **6S conversion** (`BATT_ARM/LOW/CRT` 13.2/14.0/13.2 →
23.0/21.6/21.0, capacity 4000→3000); `AIRSPEED_CRUISE` 15→20; airspeed enabled as above;
`MIS_TOTAL` 11→47; accel, compass and AHRS trims all re-calibrated.

One of them needs an answer before the next flight: **`AHRS_ORIENTATION` is back to 0.** It
was set to **6 (Yaw270)** on 8 Oct as the fix for the nose-dive launch, and `docs/status.md`
still records 6 as current. Orientation 0 plus a full recalibration is consistent with the
AIO having been remounted, and the flight flew well — which is the strongest evidence it is
right — but the repo and the aircraft now disagree about a parameter that caused a crash.
Confirm which it is so `status.md` can be corrected.

## 8. Open on your side

- **Pull the Pi-side logger sessions** (§3) — everything in §2 is unattributed without them.
- **`tailscale set --accept-routes` on the Cruza**, then ladder step 3 against
  `10.223.53.10` with the gateway up.
- **Repoint the Cruza's `/etc/cruza-path-health.json` to 100.100.0.29** and add the phone
  as a second target (§4.2). Edit the installed file with sudo and restart only
  `cruza-path-health.service`; editing the staged profile does nothing to the running config.
- **Battery thresholds and the current monitor** (§6.1, §6.2).
- **`SERIAL8_PROTOCOL = -1`** unless something belongs there (§6).
- **QuadPi install** is still pending — `10.223.79.20` was unreachable all day with RN08's
  radio off. The hard-coded `ebach` and the `--output-range`/`ProtectHome` interaction are
  as reported in the handback.
- **RN08's handheld has a stale stored config** — `encryption='psk2+ccmp'` while it
  demonstrably runs SAE. It meshes fine today; the next reboot or `wifi` restart applies
  the stale value and drops it off. Worth fixing stored-to-match-running before a flight.
- **Power RN08's radio** when you can — ladder steps 4 and 5 need both ends up.
- **Confirm the `AHRS_ORIENTATION` question** (§7).

## 9. Open on mine

- Gateway is 6/6 and the route auto-approves; nothing left there for step 3.
- **The Mini still does not boot** — two modules, two hosts, four power sources, identical
  result. Until it is resolved RN03 reaches the mesh only with the handheld occupying the
  Pi's single data USB socket, which is a bench arrangement, not a flight one.
- **Gateway-side persistent logging** is not commissioned, so there is still no far-end
  counter to pair with any aircraft-side evidence.
- R24-D `wifi-on-interval` 60 s → Off.

## 10. What not to claim

- Hop reachability is not authenticated application delivery. Observation forwarding
  remains disabled as shipped; no test observation is a flight command or proof of video
  reception.
- No video evidence exists for this flight from either end.
- Nothing on the Pi was inspected live — it was offline from 20:10 UTC. Every
  companion-side statement here comes from the FC's UART counters or from the package
  source and its README.
- Mesh reachability was not checked end-to-end today; the handheld and RN03's Pi were both
  unreachable from the gateway.
- No parameter was written, no mission uploaded and no FC command sent during this review.
