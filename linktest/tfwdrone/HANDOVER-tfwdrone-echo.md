# TFWDRONE is ready to echo â€” you do not need SSH to it

From: jbrascom (`alien03`)
Date: 22 Oct 2026
Re: your `cruza-quad-link-test` branch

Your `linktest` tool is installed on TFWDRONE and starts its echo on boot. You run
the test from your side; nothing on test day needs access to my aircraft.

## What is installed

| Item | Value |
|---|---|
| Tool | `~/linktest/linktest.py` (v1.0.0) and `plan.json`, account `jbrascom` |
| Logs | `~/linktest-logs/` |
| Service | `linktest-echo.service`, enabled, `Restart=always` |
| Command | `python3 linktest.py echo --name tfwdrone --duration 14400` |
| Python | 3.13.5 |
| Clock | synchronized (`timedatectl`), so your report can time-match my logs |

The echo binds `0.0.0.0:15700`, so it receives on both the VPN address
(`100.100.0.6`) and the mesh address (`10.223.53.30`) without a `bind` entry.
`--duration 14400` is the tool's maximum; it adds 15 minutes and exits, and the
service opens a fresh session, which your report stitches together.

## What to set in your plan.json

**Leave `tfwdrone`'s `ssh` as `CHANGE_ME`.** Your wrapper then skips it for
`deploy`, `start`, `status`, `stop` and `collect` â€” which is correct, because the
echo is already running and I will send you the logs. The sender still probes it:
`targets_from_plan` builds targets from `paths`, not from `ssh`, so
`tfwdrone/vpn` â†’ `100.100.0.6` is tested as normal.

Nothing else about the entry needs to change. `position` is still `null`; the
drone's loiter point is not fixed yet, so your report will measure range from the
Cruza's launch point. Say the word if you want a flight log from it instead.

## Two findings from verification

**1. The Cruza and the drone are relayed, not direct.** The echo's own status
record, with the Cruza online:

```json
"tailscale":{"100.100.0.58":{"peer":"tfwcruza","online":true,"path":"derp:nyc"}}
```

Later in the day the same peering showed `relay "ord"`. Every probe is therefore
making a round trip through a Tailscale DERP relay in another state, so the RTT
you measure is the relay path, not the LTE link you are trying to characterise.
Your default `rtt_p95_ms: 1000` may fail for a reason that has nothing to do with
range or height. Worth getting a direct path up before the flight, or reading the
RTT column with this in mind.

**2. UDP 15700 does reach the drone over the VPN.** README Â§2 asks for a Headscale
rule allowing `tfwcruza` â†’ UDP 15700. I sent a packet from `alien03`
(`100.100.0.29`) to `100.100.0.6:15700`; the echo logged it and rejected it as not
coming from the Cruza:

```json
"rejected":{"100.100.0.29":1},
"routes":{"100.100.0.58":{"dev":"tailscale0","src":"100.100.0.6","via":null}}
```

So the port is open through the VPN and the drone holds a route to the Cruza. The
sender's own `preflight` is still the real check, since my test could not come
from `100.100.0.58`.

## Caveat you should plan around

TFWDRONE's VPN presence is intermittent. Over about two hours it went from
`offline, last seen 12h ago`, to reachable, to `active` with traffic counters but
answering neither its VPN nor its mesh address. Its only uplink at the time was
`wlan0`. Run your `preflight` close to launch rather than relying on an earlier
pass, and treat a `no answer from echo` result as possibly the uplink rather than
the echo.

## Getting the logs

I will `scp -r` the `~/linktest-logs/*_echo_*` folders off after landing and send
them to you for `report.py`. If the test runs long enough to span sessions you
will get more than one folder; send them all through as they are.

## Verified on the bench, 22 Oct

- `systemctl is-enabled` reports `enabled`, `is-active` reports `active`, and the
  service is listening on `0.0.0.0:15700`.
- A UDP packet from `alien03` reached the running service and was logged as
  `"rejected":{"100.100.0.29":1}` — the port is open through the VPN and the
  sender filter works.
- I killed the echo with `kill -9`; systemd restarted it ten seconds later on a
  new PID, `NRestarts=1`, listening again. That is the path that keeps the echo
  up through a long wait before launch.
- **Boot start is proven.** The aircraft power-cycled on its own and the service
  came up without anyone touching it, listening within 4 s of systemd starting it.

### The clock caveat, which affects your report

The drone has **no RTC** (`timedatectl` reports `RTC time: n/a`), so at boot it does
not know the time until NTP lands. On the boot above, the echo started first and
recorded its own verdict:

```json
"clock":{"ntp_synchronized":false,"utc":"20261022T152438Z"}
```

Real time was about 15:43 — the session is stamped roughly 19 minutes early, and
the clock then jumped forward underneath the running process. Since `report.py`
time-matches this log against the Cruza's flight log, a session that starts before
NTP will silently place probes at the wrong point in the flight.

I have added an `ExecStartPre` to the unit that waits up to 120 s for
`NTPSynchronized=yes` before starting the echo, then starts anyway on timeout —
missing the test entirely would be worse than a skew. Each session records
`ntp_synchronized` in its `meta` record, so **check that field before trusting a
session's timestamps**, and discard or offset any session that reports `false`.

- The 120 s wait is in the unit and the service restarted cleanly with it, but its
  behaviour *at boot* has not been observed yet; the next power cycle will show it.
- Earlier sessions on the drone from 22 Oct are verification only. One of them
  (`20261022T152438Z`) carries the bad clock described above. The unit is enabled and symlinked into
- Today's sessions in `~/linktest-logs/` are verification only and contain no
  Cruza probes. The service opens a new session roughly every 4h15m, so expect
  several folders by test day; only the ones spanning your sender's run carry data.

## Do not hand-start the echo

The echo is a systemd service, so starting one by hand breaks it. `linktest.py`
keeps a pidfile at `~/linktest-logs/echo.pid` and refuses to run a second echo:

```
A linktest echo is already running (pid 5194). Run 'stop' first.
```

A hand-started copy takes that pidfile and UDP 15700, the service's own instance
exits 1, and with `Restart=always` it crash-loops until the start limit stops it,
leaving an echo that is running but is **not** the configured one. That happened
here once: a manual `nohup ... linktest.py echo --name tfwdrone` with no
`--duration` ran for 38 minutes while the service sat failed, so the echo on the
air had the default 4500 s lifetime and an accept list from before the plan was
edited.

Use the service instead:

```sh
sudo systemctl restart linktest-echo    # after any plan.json change
systemctl status linktest-echo
journalctl -u linktest-echo -n 20
```

`tfwdrone/allow-source.sh <CIDR>` does the whole thing: backs up the plan, adds
the source, clears a stale pidfile, and restarts the service.

## Changing the accept list

The echo answers only `plan.cruza.tailnet_ip` plus `cruza.extra_allow`. If the
Cruza's packets arrive with a different source, relayed through the mesh gateway
for instance, that address has to be listed or every probe is rejected.

Currently allowed: `100.100.0.58/32` and `10.223.58.11/32`.

The second was added at jbrascom's direction. Noting for the record that
`HANDBACK-path-health-20261020.md` 1a flags `10.223.58.11` as the **phone** slot
for roster 8 (`.10` laptop, `.11` phone, `.30` pi), and that the gateway holding
the approved `10.223.0.0/16` route is `alien03` at `10.223.53.10`. If probes over
the mesh path come back rejected, that address is the first thing to check.

## Removing it afterwards

The service runs whenever the aircraft is powered, which also means it logs during
unrelated flights. I will take it off after the test:

```sh
sudo systemctl disable --now linktest-echo
```
