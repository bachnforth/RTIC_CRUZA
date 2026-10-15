# Cruza hybrid LTE + Doodle mesh: session handover — 2026-10-14

Desk session only. **Nothing on the Pi was touched, inspected live, or changed.**
No FC parameter was read or written. Next bench session: 2026-10-15 ~10:30.

## What this session actually did

Read the existing documentation and source, confirmed this laptop cannot reach
the Pi, and recorded the findings below. The local checkout was fast-forwarded
`dee610b -> aca8886` (4 commits, already on `origin/main`); no other repo change.

## Blocker: no route to the Pi from this laptop

This laptop is `alien03` / `100.100.0.29`, user `jonathan.l.brascom.mil@`, on the
correct control server (`tailscale debug prefs` reports ControlURL
`https://headscale.rotopter.com`). The Pi is not visible to it:

| Probe | Result |
|---|---|
| `tailscale ping 100.100.0.58` | `no matching peer` |
| `tailscale whois 100.100.0.58` | `peer not found` |
| `ping -n 2 100.100.0.58` | 100% loss |
| `ssh ebach@100.100.0.58` | connection timed out (8 s) |

`tailscale status` lists 11 peers; `tfwcruza` (.58), the phone (.57) and
`alien08` (.23) are **not among them**. These nodes sit under a different
Headscale user and the policy does not expose them to this node. This is an ACL
or namespace question for the Headscale admin, not a Pi fault — the Pi may well
be up and reachable from `alien08`. **Every live recheck, measurement and bench
step in the task brief is gated on resolving this.**

## Documentation discrepancies found

Two documents named in the task brief do not exist on `origin/main`:

| Named in brief | Actual |
|---|---|
| `docs/mission-hat-handover-2026-10-14.md` | does not exist |
| `docs/qgc-lte-testing-2026-10-14.md` | does not exist |
| `docs/pi-companion-audit-2026-10-14.md` | exists, read |
| `companion/README.md` | exists, read |

The nearest match for both missing names is `docs/qgc-lte-handover-2026-10-14.md`,
which was read in their place, along with `docs/lte-integration.md`.

## Brief vs. committed docs — recheck these live before trusting either

The brief lists as already verified several items the committed docs record as
**pending**. The brief may simply be newer than the commit, but nothing here
confirms that, and the brief itself says not to trust the docs as current.
Resolve each by live inspection before building on it:

| Claim in brief | Committed docs say |
|---|---|
| cruza-router listens on `100.100.0.58:14560` | "router inactive, `/etc/cruza/firewall.nft` absent; activation pending" |
| nftables admits only the partner's phone | firewall file absent at last live check |
| Android QGC 5.0.8 connects | "app version and visible video still unconfirmed" |
| QGC downloaded the full parameter list | "full parameter download ... still pending" |

## Finding 1 — the companion is single-peer by construction

`companion/cruza.py` cannot serve two phones or any mesh peer without changes.
This is a design limit, not a configuration gap:

- `config["android_ip"]` is a **scalar**, used by the router, the video sink and
  the firewall generator alike (`cruza.py:45`, `:60`, `:79`;
  `activate-router.sh`; `configure-android.sh`).
- `tail_ip()` (`cruza.py:52`) **rejects any address outside `100.64.0.0/10`**.
  Mesh addresses (`10.223.0.0/16`) fail validation in the router, the video path
  and the firewall generator. Mesh support needs a separate validator, not a
  loosened one — the tailnet restriction is doing real work.
- `router_text()` (`cruza.py:59`) emits exactly one `UdpEndpoint`, `Mode = Server`.
- `video()` (`cruza.py:78`) uses a single `udpsink host=...`.

Consequence for item 4 (Jonathan's phone on 14561) and for mesh delivery: both
need an endpoint **list** — per-entry address, MAVLink port, and whether video
goes to it. Video fan-out should be one `multiudpsink` with a client list behind
the single existing `rpicam-vid` hardware encode, which keeps the Zero 2 W to one
encoder and no transcoding. `activate-router.sh` currently refuses to replace an
existing `inet cruza` table, so adding a second phone means a reviewed table
replacement, not a re-run.

## Finding 2 — the mesh physical path is probably already solved

`rekon-mesh/pi/mesh-join.sh` shows the Doodle mini-OEM presents to a Pi as a
**USB-Ethernet adapter**: USB ID `0424:` (Microchip/SMSC LAN9500A), driver
`smsc95xx`. So no separate USB-Ethernet dongle is needed — the radio *is* the
USB NIC.

The open question is where it plugs in. Per the companion audit, the SIM7600G-H
HAT (B) carries a **Terminus hub `1a40:0101`** whose upstream is the Pi's USB OTG
port through the pogo contacts, with **USB1/USB2 as downstream peripheral ports**.
That is exactly the topology needed: the mini should enumerate behind that hub on
USB1 while the modem stays on `1e0e:9001`. Note the earlier failure mode — a
cable from the Pi's data port *into* HAT USB1 broke modem detection, because that
drives a downstream port backwards. The mini goes into USB1 as a peripheral; the
Pi data port stays empty. **Bench-verify with `lsusb -t` before trusting this.**

`mesh-join.sh` also already solves the routing hazard: the mesh connection is
created `ipv4.never-default yes` with no gateway, matched **by driver** so it
survives a radio swap, and the script fails loudly if the default route lands on
the mesh. That is the right pattern for the Cruza, where LTE must stay the
default route.

## Finding 3 — existing mesh parameters (from rekon-mesh, to be confirmed)

| Setting | Value |
|---|---|
| Band / scenario | 915v4 MHz, mesh on radio0 |
| Mesh ID | 666 |
| Channel / bandwidth | 20 (907 MHz) / 10 MHz |
| Encryption | WPA3-SAE (password held by Josh; never in chat or git) |
| Operating distance | 2000 m |
| Addressing | flat `10.223.0.0/16`, no DHCP, no gateway, no internet |
| Host blocks | `10.223.5N.x` by roster: laptop .10, phone .11, Pi .30 |
| Radio management | `10.223.196.1NN` handheld, `.14N` mini |
| TX power | bench 16 dBm + fan; field max 32 dBm, verified over ssh |

915 MHz is clean against both the 2.4 GHz ELRS link and the LTE bands, which is
the result we want — but `rekon10-build/DOODLE-INTEGRATION.md` records that the
mini's **band SKU was never read off the hardware**. Confirm before planning RF.

Precedents worth copying rather than re-deriving: `rekon-mesh/RN03/mavlink-router.conf`
(FC UART + per-GCS UDP endpoints) and `rekon-mesh/RN03/doodle-qos.nft` (DSCP: MAVLink
EF, video AF41, so a video burst cannot starve telemetry).

Note the mini-OEM load: **5 W RX, 14 W peak, 2 W standby, 102 g**. Per the Rekon
integration notes that needs its own BEC off the pack, not a shared rail.

## Finding 4 — hypotheses for the two open bugs

Neither is diagnosed. These are the cheapest things to test first, in order.

**Router stall, UART TX stuck at 0.** The single endpoint is `Mode = Server`
(`cruza.py:65`). A server endpoint has no destination until a GCS sends to it, so
until QGC's first packet arrives there is nothing to write toward the FC and TX
is *correctly* 0. It only becomes a fault if TX stays 0 **after** QGC traffic
reaches the Pi. Distinguish the two:

1. `sudo nft list table inet cruza` and `ss -lunp` — is the listener bound to the
   tailnet IP, and is the rule admitting the phone's source address?
2. `sudo tcpdump -ni tailscale0 udp port 14560` while QGC connects — does the
   phone's packet actually arrive, and from which source address?
3. Only if packets arrive and TX is still 0, suspect the router or the UART.

A dropped first packet also produces this exact symptom, so rule the firewall out
before touching anything else.

**97–98% "sequence loss".** mavlink-router counts gaps in the MAVLink sequence
byte per source. Candidate causes, cheapest first:

1. **Counting across merged sources.** More than one (sysid, compid) pair on the
   same link — ArduPilot components plus the GCS's own 255/190 heartbeats — each
   with an independent sequence counter, read as one stream. Expected to look
   like near-total loss.
2. **Genuine UART framing loss**, which the 2026-10-14 capture argues against:
   21,274 bytes parsed into 665 CRC-valid frames with no note of bad CRCs.
3. **Stats counted before the endpoint is learned**, i.e. the same root as the
   stall above.

Diagnose with `journalctl -u cruza-router` statistics broken out per endpoint, and
cross-check against QGC's MAVLink Inspector message rates. If the inspector shows
steady 4 Hz heartbeats and smooth attitude while the counter reads 97%, the
counter is an artifact, not a link problem. Confirm against the mavlink-router v4
source on the Pi — do not assume the counter's semantics from memory.

## Open questions — answer before any radio-dependent config

1. **Pi access.** Add `alien03` / `100.100.0.29` to the Headscale policy for
   `100.100.0.58`, or run the commands yourself and paste output, or keep this
   session to design work only?
2. **Which radio, which band?** mini-OEM on the 915v4 recipe, a 2.4 GHz mini-OEM
   (conflicts with ELRS — your own notes say do not fly it), or an RM-1700-22W3?
   Model, band range and firmware version, read off the hardware.
3. **Cruza's roster row.** It is absent from `rekon-mesh/roster.conf` (rows exist
   for 3 = RN03, 8, 18 = Josh). Proposed: new row 5 — Pi `10.223.55.30`,
   mini management `10.223.196.145`.
4. **Mesh peers for the test**, each with firmware, current `SYSID_THISMAV` and
   video setup. `rekon10-build/DOODLE-INTEGRATION.md` is marked "plan only —
   nothing installed, nothing flown" as of 18 Sep 2026, so confirm what is
   actually live rather than assuming RN03 is on the air.

## Proposed order for the bench session

Props off. One link at a time, verified before the next is added.

1. Restore Pi access, then recheck live state against the brief's claims:
   `systemctl status cruza-firewall cruza-router`, `ss -lunp`,
   `sudo nft list table inet cruza`, `nmcli device status`, `tailscale status`,
   `vcgencmd get_throttled`. Confirm the AIO is powered and disarmed.
2. Item 1 of the brief: confirm video actually paints on the partner's phone and
   record latency. Nothing downstream is worth building until a picture exists.
3. Item 3: the stall and the loss counter, using the steps above. Cheap, and it
   decides whether the current single-phone path is sound enough to extend.
4. Item 2: repeat QGC + video with Pi Wi-Fi disconnected, using the timed
   `systemd-run` restore from the QGC/LTE handover so the Pi cannot be stranded.
5. Item 4: second phone on 14561 / SYSID 254, per-phone firewall rules, video to
   both. Requires the `cruza.py` endpoint-list change in Finding 1 and Jonathan's
   phone enrolled at `100.100.0.60` first.
6. Mesh work only after 1–5 pass and the four questions are answered.

Unchanged throughout: `FS_GCS_ENABL=0`, so losing a link does **not** trigger
RTL. No arming, no mission upload, no mode change, no motor run. No FC parameter
written without explicit approval.
