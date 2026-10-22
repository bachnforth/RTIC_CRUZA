# Laptop VPN-to-mesh application gateway

The relay is a normal background Python process on alien08. It changes no
routes, DNS, adapter configuration, forwarding preferences, firewall rules,
VPN advertisements, or internet sharing. Existing subnet-routing settings
from earlier work remain as they were. Docker is not installed or required.

Current fixed mapping:

```
Cruza 100.100.0.58
  -> laptop VPN 100.100.0.23:15710/UDP
  -> laptop mesh 10.223.58.11 (separate socket per sender)
  -> QuadPi 10.223.79.20:15700/UDP
```

A second fixed mapping is now available for TFWdrone:
100.100.0.23:15711/UDP -> 10.223.53.30:15700/UDP, also sourced from
10.223.58.11. It has not passed an application round-trip check; the partner
must start the receiver with that exact source permitted. The updated package
is output/tfwdrone-relay-install-2026-10-22.zip. No scripts were written remotely
to TFWdrone. Cruza's dual-relay-plan.json contains both gateway destinations;
the original relay-plan.json still limits testing to QuadPi.

Replies retrace the relay session. QuadPi sees 10.223.58.11 as the source;
it does not need internet, VPN connectivity, a default gateway, or a return
route to Cruza. The test receiver's separate relay-plan.json permits only
Cruza's VPN source and the laptop's exact mesh source. No writes to TFWdrone.

Incoming sockets bind only the laptop's VPN address. Only Cruza's VPN IP is
accepted. Destinations are fixed in mesh-relay.json, not supplied by senders.
There are at most 64 sender sessions, expiring after 120 seconds of inactivity.
The existing VPN policy permits traffic addressed to the laptop itself, so
this design does not require granting Cruza access to the quad mesh subnet.

## Operation

From the repository directory:

```powershell
.\linktest\mesh-relay.ps1 start
.\linktest\mesh-relay.ps1 status
.\linktest\mesh-relay.ps1 stop
```

The process is hidden. Logs and status live under output/mesh-relay.
It is not a startup service: rebooting the laptop stops it. To undo this new
gateway, stop the process; no network configuration restoration is necessary.
Addresses in mesh-relay.json must still be assigned when it starts. The launcher
checks process identity before stopping it, rather than trusting a stale PID.

## Test tools on Pis

The test variant is ~/linktest/relay-linktest.py with relay-plan.json.
Original linktest.py and plan.json on each Pi were preserved.

QuadPi receiver:

```sh
cd ~/linktest
python3 relay-linktest.py echo --name quadpi --plan relay-plan.json
```

Cruza sender:

```sh
cd ~/linktest
python3 relay-linktest.py preflight --plan relay-plan.json
python3 relay-linktest.py send --plan relay-plan.json --duration 60
```

Stop a test process with the same tool's `stop --role echo` or `stop --role sender`.
The laptop relay remains running independently of those processes.

## Scope and verification

This mapping carries dedicated UDP link-test traffic, not MAVLink or video.
Additional applications require explicit endpoint/port mappings and receiver
configuration. Do not direct flight-control traffic into the link-test receiver.
The relay is an application gateway, not an Ethernet bridge or general IP router.
It does not make ICMP ping to the quad mesh address succeed from Cruza.

The loopback test checks isolated client replies and rejection of other sources.
The first live preflight on 22 October passed 10/10 packets, median RTT 137 ms,
with Cruza Wi-Fi down. QuadPi had only its eth0 mesh route and no default route,
so its independent VPN internet path was not used. This is a ground connectivity
check, not a flight reliability qualification. Sustained results are saved with
the link-test report separately.

The subsequent 65-second test delivered 324/326 probes (99.4%), median RTT
133 ms and 95th-percentile RTT 196 ms. Longest probe loss was 0.2 seconds.
One of two bulk bursts completed (50%, below the 90% target), so the report
correctly returns FAIL despite passing probe delivery and latency checks.
Median burst throughput was 517 kbit/s. No flight log was supplied. The report
also estimated QuadPi's clock about 102 seconds behind Cruza; time synchronization
needs attention before flight-log correlation. Sender and echo test processes
were stopped, while the laptop relay was restarted and remains running.
Report: linktest-results/mesh-relay-2026-10-22/report/report.html.

## Full round-trip retest

Run 20261022T154331Z-yciu lasted 125 seconds. QuadPi's actual reception logs
confirm 616/626 probes (98.4%) arrived; Cruza's logs confirm replies returned.
Median RTT was 134 ms, p95 182 ms, longest probe outage 0.4 seconds. Three of
four bursts completed (75%, below the 90% target); median throughput 516 kbit/s.
The report's overall verdict remains FAIL on burst completeness, rather than
a claim of flight readiness. QuadPi Wi-Fi was down and it had only the mesh
subnet route, with no internet default route. An 18-second packet capture on
QuadPi eth0 saw 137 test UDP packets from laptop 10.223.58.11 and 87 replies
back to that same mesh address (burst chunks do not each generate replies).
This independently establishes both mesh directions. Local relay counters
before adding TFWdrone are saved in output/mesh-relay/quadpi-roundtrip-counters.json.

Report: linktest-results/roundtrip-2026-10-22/report/report.html.
QuadPi's receiver was stopped after collection; the laptop relay remains running.
TFWdrone began answering mesh pings during this retest, but its subsequent
Cruza-origin application check produced 13 relay forwards and zero replies.
