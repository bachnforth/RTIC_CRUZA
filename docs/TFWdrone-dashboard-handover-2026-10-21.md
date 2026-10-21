# TFWdrone dashboard telemetry handover

Copy the prompt below into the coding assistant working on TFWdrone. This is an installation brief, not a shell script. No software has been installed on TFWdrone by preparing this handover.

---

Install an optional, read-only fleet-dashboard telemetry observer on my aircraft Pi, TFWdrone. Do the software work using existing authorized access; ask me only for physical tasks or genuinely missing access. Inspect the aircraft's actual configuration before choosing an implementation.

Context verified October 21, 2026:

- TFWdrone is online on our shared Tailscale/Headscale VPN at `100.100.0.6`. Verify this address and hostname again.
- Our dashboard laptop is `100.100.0.23`; its dashboard is currently local-only at `http://127.0.0.1:8765/`. The Pi should not try to reach that loopback URL.
- The dashboard already supports Cruza and quadpi. The visible third card is **TFW drone**, with internal source key **rn03**. It is currently an unconfigured placeholder.
- Quadpi is a different aircraft at VPN `100.100.0.10`, mesh `10.223.79.20`. Do not install on quadpi or use its telemetry as TFWdrone's data.
- TFWdrone uses a wearable mesh radio; do not assume its current radio IP, UART, autopilot, camera, or services from another aircraft's configuration.

Preserve standalone operation:

1. RC flight, existing QGC/LTE/mesh connections, video, missions, and flight-control services must keep working when the dashboard, laptop, observer, or mesh is absent.
2. Do not change flight-controller parameters, system/component IDs, stream rates, failsafes, modes, routes, firewall policy, or existing command filtering. Do not send MAVLink requests, heartbeats, commands, arm/disarm actions, or mission writes as part of this observer installation.
3. Never open a second reader on the flight-controller serial port. Prefer passive observation of an existing aircraft-to-GCS MAVLink network stream. If that is unavailable, inspect the existing bridge and prepare a best-effort, nonblocking loopback mirror of its received aircraft bytes. Do not restart or modify a flight-related bridge while the aircraft could be operational; report any required maintenance step before doing it.
4. The observer must be an independently managed service with no dependency added to the router, video, or flight services. Use bounded memory, bounded output, low priority, and resource limits. A full queue, missing viewer, or failed observer must drop observation data without delaying normal traffic.
5. Verify existing standalone services first. Then enable only the optional observer, with a documented single-command disable and rollback. Do not reboot the aircraft for this work.

Inspect and record:

- Hostname, VPN IP, OS, existing authorized SSH username, and SSH host-key fingerprint.
- Existing MAVLink bridge/router, its service definition, actual telemetry interfaces/endpoints, and aircraft heartbeat system/component IDs. Keep credentials and private configuration values out of reports.
- Whether fresh heartbeat, attitude, position/GPS, battery, and mission-status messages actually exist on the current stream. Missing fields must remain unavailable; do not invent values or alter FC settings to obtain them.

Implement this telemetry contract, so our laptop dashboard can connect later:

- Passively observe only this aircraft's own telemetry. Filter network packets by the verified interface, aircraft source address/port and intended telemetry flow; do not collect unrelated VPN or mesh traffic.
- Preserve complete original MAVLink 1/2 frames, including their checksum and any MAVLink 2 signature. Do not rewrite source IDs. The laptop validates CRC and aircraft identity.
- Forward these message IDs when available: `0, 1, 24, 30, 33, 42, 46, 74, 147, 242, 245, 253` (heartbeat, status, GPS, attitude, global position, mission current/reached, VFR HUD, battery, home, extended state, status text).
- Limit ordinary messages to at most two per second per message type. For STATUSTEXT, preserve multipart fields and allow a bounded burst, for example 20 messages per 10 seconds. Do not emit a backlog of stale telemetry.
- Emit newline-delimited UTF-8 JSON datagrams to loopback UDP **127.0.0.1:15611** only. Each record must remain below 2048 bytes. Use the following shapes:

  Metadata at startup and every five seconds:
  `{"boot_id":"<actual /proc/sys/kernel/random/boot_id>","source":"rn03","passive":true}`

  Each selected complete MAVLink frame:
  `{"frame":"<original complete MAVLink frame as hexadecimal>"}`

- Install an unprivileged relay at `/opt/cruza-telemetry-relay.py`. Invoked as `python3 /opt/cruza-telemetry-relay.py --port 15611`, it must bind that loopback address/port, validate bounded incoming JSON, and write the same newline-delimited records to stdout. Emit `{"observer_waiting":true}` after five seconds without input. Do not send MAVLink or bind public interfaces. Diagnostic messages belong on stderr, not stdout. Handle stdout backpressure with bounded memory and terminate on a broken pipe or prolonged stalled output.
- The laptop will start this relay over SSH under its existing viewer-lease wrapper: stdin receives periodic lease text; EOF or 15 seconds without a lease terminates the relay. Do not create a permanently running relay or a second UART reader. Permit only one active relay on that loopback port; avoid orphan processes during reconnects.
- Name the optional observer service `cruza-telemetry-observer.service` if that name is unused. Suggested limits are `Nice=19`, `CPUQuota=5%`, `MemoryMax=24M`, bounded restarts and logs. Adapt limits to the verified runtime. If packet capture needs privileges, minimize capabilities and drop privileges after opening the capture socket. Do not give the relay elevated privileges.
- Provide one documented disable command, such as `sudo systemctl disable --now cruza-telemetry-observer.service`, adjusted to the final service name. If an optional bridge mirror was added, separately document how to remove it safely; disabling the observer must not stop the bridge.

Verify with evidence:

1. Show fresh valid aircraft heartbeat frames and their actual system/component IDs through the SSH relay, without transmitting to the autopilot.
2. Show which other requested message types are present. Distinguish a working observer with absent FC messages from a transport failure.
3. Close the SSH viewer and confirm the relay exits and leaves no listener on 15611. Confirm the observer remains bounded when no viewer is connected.
4. Stop and restart only the optional observer, checking that existing router/video services remain running. Simulate loss of the optional observer/SSH session; do not disable the aircraft's network interfaces or interrupt its existing QGC connection for testing.
5. Do not claim laptop dashboard integration is complete: its rn03 placeholder still needs to be replaced with a real source configuration on the laptop.

Return this completion report for the laptop operator:

```text
TFWdrone installation result: COMPLETE / BLOCKED / PARTIAL
Verified hostname and VPN IP:
Existing authorized SSH username:
SSH ED25519 public host-key fingerprint (SHA256):
Actual FC system ID / component ID:
Observer service name and status:
Capture source / interface / endpoint or mirror:
JSON source key: rn03
Relay path: /opt/cruza-telemetry-relay.py
Relay command: python3 /opt/cruza-telemetry-relay.py --port 15611
Fresh heartbeat verified:
Other message types verified / missing:
Viewer-disconnect cleanup verified:
Standalone services preserved:
Changes made, backup locations, disable and rollback commands:
Existing camera/video source, format and endpoint, if inspected:
Remaining access or installation blockers:
```

Return only public identification/access details, never passwords, tokens, VPN enrollment keys, private SSH keys, or full secret-bearing configurations. The laptop operator must verify the SSH host fingerprint before trusting the new host. Use an existing authorized public key or the team's established SSH provisioning process; do not weaken host verification, SSH authentication, or VPN ACLs.

Video is a separate follow-up. Inspect and report its existing source, but do not install a second encoder, repoint the pilot's stream, or claim telemetry installation enables video. Any future dashboard video copy must be optional and preserve the original camera/QGC path.
