# Android QGC / LTE bench continuation — 2026-10-14

Continues [the handover](qgc-lte-handover-2026-10-14.md).

## Final outcome

The owner confirmed that QGC's parameter download completed after reconnecting.
Android QGC 5.0.8 (64-bit) now connects through the private Pi endpoint with
bidirectional routing. Full parameter export/count comparison is not yet saved.
The latest continuation is [the mission and HAT-health handover](mission-hat-handover-2026-10-14.md).
The observations below are historical snapshots, including superseded failures.

Final live check at 20:38:48 UTC: router/firewall and both monitoring timers
active, video inactive, RN08 connected, Wi-Fi default metric600 preferred over
LTE metric700. Temperature 48.9 C, available RAM277 MiB, no swap use,
`get_throttled=0x0`. Router UART receive statistics since its last restart:
26,825 handled, zero CRC/sequence errors, 1,200 messages transmitted to UART.
Android sequence-loss counter still reported98%; investigate rather than
equating this counter with VPN packet loss.

## Live preflight

At 19:46 UTC, private-IP SSH worked. SIM7600 was enumerated and
NetworkManager reported `cruza-lte` connected. RN08 Wi-Fi was connected,
with default metric 600; LTE `wwan0` default metric was 700. Android
100.100.0.57 answered a private-network probe through the Miami relay.
This does not establish QGC or LTE-only application acceptance.

Live config matched the handover: UART 115200, phone 100.100.0.57,
MAVLink UDP 14560, video UDP 5600, economy profile, 120-second video limit.
Config validation passed. Temperature was 49.9 C; available memory 295 MiB;
swap use zero; `get_throttled=0x0`.

## Router activation

The first owner-run activation failed at `nft --check`: both closing braces
were emitted on one line, producing an unexpected-brace syntax error.
The script now emits table/chain declarations and closing braces on separate
lines. The corrected `companion/activate-router.sh` was copied to the Pi;
`bash -n` passed. The owner reran activation with sudo.

At 19:49:54 UTC, live inspection confirmed:

- `cruza-firewall` enabled, active/exited, success since 19:49:03 UTC.
- `cruza-router` enabled and running since 19:49:07 UTC.
- UDP listener bound to `100.100.0.58:14560`; TCP disabled in router config.
- Installed firewall file allows UDP14560 from Android 100.100.0.57 only
  through tailscale0 and drops other traffic to that port. Service success
  confirms loading; a separate privileged live-table dump remains pending.
- Router UART statistics: 3,921 handled messages, zero CRC errors and zero
  reported sequence loss. No separate process opened the UART.
- Android UDP endpoint had zero received/transmitted messages at this check;
  QGC had not yet been verified connected.
- `get_throttled=0x0`.

## Session observations and remaining acceptance

At 20:31 UTC the owner's passive capture showed phone 100.100.0.57:14550
sending to Pi :14560: 15 heartbeats, 53 parameter-read requests, 31 stream
requests and two COMMAND_LONG frames, all with source 255/190. Command IDs
were not decoded; these were QGC-generated, not diagnostic-generated commands.
Source-ID conflict is not established.

At 20:32:53 UTC an eight-second debug attempt failed because stopping the
normal service removed `/run/cruza/router.conf`. The debug process fell back
to its default TCP5760 listener for the bounded interval. Normal service was
restored and TCP5760 absence verified. Diagnostic corrected to copy config
outside the service runtime directory and explicitly pass `-t 0`. No client
connection to that transient listener was observed in the inspected logs.

Corrected debug at 20:33:24 UTC decoded phone parameter requests to target1/1;
requests initially preceded the first UART frame, then UART endpoint learned
1/1 and accepted phone messages. Actual UART writes were logged. Normal router
was restored by 20:33:32 UTC. At 20:34:51 UTC it had transmitted 469 messages
to UART, with UART receive CRC/sequence counters zero since restart. The prior
stalled routing state cleared on restart; its original cause remains unknown.

The packet observer's original ETH_P_IP socket captured RX only. It was
corrected to ETH_P_ALL to include TX; earlier empty-return observations must
not be interpreted as proof of absent outbound packets. The 20:34:34–20:34:44
UTC corrected observation saw 32 phone-to-Pi packets and 844 Pi-to-phone
packets, including ten FC1/1 heartbeats and telemetry. No parameter requests
or PARAM_VALUE replies appeared in that window. QGC was asked to reconnect
and retry its download; the owner subsequently confirmed completion.

The corrected 20:35:06–20:35:36 UTC capture saw 91 phone-to-Pi packets,
2,541 Pi-to-phone packets and one FC1/1 PARAM_VALUE header. This establishes
that a parameter-value frame reached the phone endpoint, but its contents and
correlation with a fresh request were not captured in that observation.

At 20:26 UTC the owner reported QGC stuck at "Downloading". Live phone probe
succeeded directly in 88 ms. Router Android endpoint counters were increasing
(5,890 handled, 78,224 transmitted), but UART transmitted remained zero.
The return path through the router is therefore unresolved. Android cumulative
sequence-loss reporting remained 97%; this alone is not a measured packet-loss
rate on the VPN. Phone MAVLink source ID/forwarding settings and a passive header
summary were requested to distinguish an ID conflict or loop from another
routing issue. The observer now summarizes candidate frame-header source IDs
and message IDs without retaining aircraft payloads; it does not validate CRCs.
Privileged capture requires the owner to renew sudo credentials in their Pi
terminal. Wi-Fi/video acceptance remains deferred until parameter reads work.

At 20:14 UTC the owner confirmed the phone was connecting. The saved-link
screenshot previously showed the server address in the Add Server entry field;
the owner was guided to add/save it and disable UDP auto-connect under Comm
Links. The owner confirmed phone IP 100.100.0.57. Exact corrective step is not
yet confirmed.

Live router stats at 20:14:43 UTC showed Android UDP handled 1,382 messages and
transmitted 20,078 messages (642 KB). UART transmission remained zero in this
snapshot, so a routed FC parameter reply is not yet established. Android
endpoint reported 97% sequence loss (64,786), which needs investigation;
do not treat the connected display as combined acceptance. UART cumulative
stats showed one CRC error and 510 sequence losses since router startup.
Video was inactive and `get_throttled=0x0`.

The owner asked about simultaneous QGC phones. Current policy still permits
only 100.100.0.57. mavlink-router v4 UDP server endpoints send to the last
sender address/port, so expanding an allow-list on the existing single server
endpoint alone would not provide stable simultaneous receivers. Separate
endpoints/ports and distinct QGC MAVLink system IDs are the proposed approach;
no second phone or policy expansion has been configured.

At 19:57 UTC the owner reported no Android QGC connection. The owner reports
QGC version 5.0.8, 64-bit. Live privileged `nft list table inet cruza` confirmed
the intended phone-only rule was loaded. Router remained active and receiving
UART messages without reported CRC errors; Android endpoint counters remained
zero. A phone VPN probe succeeded through the Miami relay in 146 ms.

A passive, metadata-only tailscale0 observation from 19:58:07–19:58:37 UTC
saw no UDP packets on ports 14550, 14560 or 5600. A subsequent 15-second
observation saw a deliberate laptop diagnostic datagram to the unused Pi port
14550, confirming the observer could see private-network UDP. This probe did
not reach the router/FC. No phone traffic was observed in those windows;
this does not establish whether QGC was reconnecting during capture or whether
QGC settings, Android VPN inclusion, or network policy prevented delivery.
Saved phone link settings and heartbeat emission remain to be checked.

Owner was asked to connect Android QGC with UDP listening port 14550 and
explicit server 100.100.0.58:14560, and report version and live disarmed state.
Phone connection and parameter-download completion are now owner-confirmed.
Saved parameter export/comparison, mission download, actual video picture,
and application traffic with Pi Wi-Fi disconnected remain pending.
No Wi-Fi disconnect was performed in this continuation. Diagnostics generated
no aircraft commands. QGC's automatic protocol requests were routed; no explicit
arming, motor, mode, parameter-write, mission-upload or flight-safety changes
were issued by the agent. Video remains pending a ready viewer and bounded start.
