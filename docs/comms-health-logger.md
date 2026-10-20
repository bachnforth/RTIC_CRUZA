# Automatic communications health logger

`companion/comms-health.py` extends the bounded flight-health sampler with a
continuous boot service, packet-observer recovery, video RTP metadata and rotating
storage. The existing bounded recorder remains available separately.

## Install and verify

Files are staged in `/home/ebach/companion/`. Run on the Pi:

```bash
sudo bash /home/ebach/companion/install-comms-health.sh
systemctl is-enabled cruza-comms-health.service
systemctl status cruza-comms-health.service --no-pager
journalctl -u cruza-comms-health.service -n 15 --no-pager
```

The installer copies source into root-owned `/opt/cruza-comms-health/`, installs
the systemd unit and enables/starts only this logger. It does not restart the
router, camera, LTE, VPN or flight controller. Re-running updates only the logger.
No reboot is required to start logging. Future startup is specified by
`WantedBy=multi-user.target`; actual cold-boot verification requires a later
owner-coordinated power cycle.

The service runs as ebach with CAP_NET_RAW for passive observation and journal
group access. It has a read-only filesystem except its log directory and private
temporary directory. No password, root login or persistent sudo exception is
installed. It never opens UART, changes the modem, resets a service/network, or
sends aircraft commands. Short internet/VPN probes are intentional diagnostics.

## Evidence recorded

Samples target a 10-second cadence. Modem and CLI calls have bounded subprocess
timeouts; slow calls can extend the interval. Raw cumulative counters support
later delta/rate calculations. Every sample has UTC, monotonic time and boot ID,
so clock changes, reboots and counter resets can be distinguished.

- LTE modem presence, connection/registration, signal quality and any available
  extended signal values; LTE interface byte/error/drop counters and routes.
- NetworkManager device states; internet ping explicitly bound to LTE once per
  minute; phone VPN path probe once per minute; peer direct/relay metadata.
- Passive MAVLink UDP counts in each direction; CRC-checked FC1/1 heartbeats,
  armed/mode state, heartbeat age and maximum observed interarrival gap.
- Router endpoint counters; router, video, modem/network/VPN service states and
  restart counters; bounded warning/error event categories with timestamps.
- Video egress packet counts, RTP sequence metadata, SSRC, cumulative byte/packet
  counts, last-seen age and maximum observed gap; phone ICMP-unreachable count
  (all observed phone-originated destination-unreachable codes, not video-only).
- Pi temperature, throttling/undervoltage flags, memory, CPU ticks, load, uptime,
  time synchronization and filesystem free bytes.

Observer retries every two seconds if Tailscale is absent or recreated. Logging
starts without waiting indefinitely for internet. Process failures restart after
10 seconds. No automatic modem/network recovery is performed by this logger.

No video/MAVLink packet payload files, GPS positions, SIM identifiers or
credentials are retained. Camera pixels are never saved by this service.

## Retention and retrieval

Files live in `/home/ebach/cruza-comms-health/comms-*.jsonl` and are accessible to
the owner. Each approximately 4 MiB segment starts with session/config metadata.
Aggregate retention is 128 MiB; oldest matching log segments are removed as the
limit is crossed. Files unrelated to the logger are left alone. Logging skips
samples below 256 MiB free disk and records a skipped count after space returns.
Samples are flushed and fsynced. Abrupt power loss can still interrupt the latest
write; an absent end record means the process did not close normally.

After a flight, copy the relevant session segments using the existing private
SSH/scp credentials. Retention is size-based, not a promised number of days.
Preserve evidence promptly. Do not run the old bounded recorder simultaneously
unless an additional capture is deliberately needed.

To stop and disable only this logger:

```bash
sudo systemctl disable --now cruza-comms-health.service
```

## Interpretation limits

This is Pi-side evidence, not instrumentation of every device. Outbound packets
prove transmission from the Pi, not phone reception, decoding, display or video
latency. A VPN probe is not a QGC application acknowledgement. Sequence steps
are not end-to-end packet-loss estimates. Router flow counters include QGC's
normal protocol requests. Extended LTE metrics may be unavailable; the allowed
modem band set is not the serving cell band.

ELRS RF quality, partner-phone/backpack delivery and physical wiring/power margin
need separate AIO/ground-side evidence. If the phone is unreachable, Pi logs alone
may not distinguish phone power-off, lost cellular service, VPN disconnection or
a blocked app. AIO DataFlash and phone QGC logs remain useful corroboration.

Five offline tests cover retention/low-disk behavior, RTP payload minimization,
sequence wrapping, ICMP metadata, socket retry, heartbeat CRC and modem data
minimization. They passed on the laptop and Pi. An unprivileged live smoke run
collected modem/VPN/resource samples; passive capture correctly reported missing
permissions pending installation of the capability-bearing systemd service.

## Installed verification — October 19, 2026, 14:15 CDT

Owner ran the staged sudo installer. Live verification confirmed service enabled,
active/running, exit status zero, zero restarts and CAP_NET_RAW present. Log samples
were growing at the target cadence with `udp.error=null`, readable event journals
and synchronized time. One 10-second interval observed 815 outbound telemetry
datagrams, 29 inbound phone datagrams and 367 outbound video datagrams. Fresh
CRC-checked FC1/1 heartbeats reported disarmed RTL. Video RTP metadata was fresh;
LTE registered/connected with signal-quality sample 67%, and phone peer active.
These are short bench observations, not a flight reliability measurement.

Files are under `/home/ebach/cruza-comms-health/`; the initial session is
`13189b03-da6f-44dd-b8f4-5a119f1fefc7-977099547941-1502`.
No reboot was performed; cold-boot startup remains to be observed at the next
normal power cycle. The service is enabled for that startup.
