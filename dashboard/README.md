# Cruza / RTIC fleet dashboard

Open **http://127.0.0.1:8765** on this laptop. Both camera pictures were verified
in the browser on 2026-10-15. The viewer is local-only and has no flight controls,
cloud hosting, recording or external assets.

To reopen after stopping/restarting the laptop, double-click
`Open video dashboard.cmd` in this folder, or run `start-dashboard.ps1`.
It uses the existing bundled Python runtime; pass `-PythonPath` if that runtime
moves. `stop-dashboard.ps1` stops only the laptop viewer and its extra streams.
No administrator privileges are needed to launch it.

## How to use it

- Keep the laptop's built-in Wi-Fi on its internet hotspot/VPN connection.
- Keep Alfa Wi-Fi 2 on RN08 Handheld with its existing mesh address.
- quadpi connects to RN03 via USB-D; RN03 and RN08 communicate across the mesh.
- Power the cameras/Pis. Each panel reconnects independently if a link drops.
- **Pause video** stops both additional SSH video copies immediately.
  **Resume video** restarts them. Telemetry continues while video is paused.
  Closing the last dashboard page stops copies
  after approximately 12 seconds. Camera encoding and original QGC transmission
  continue on the aircraft. Multiple tabs share one copied feed per aircraft;
  another open tab can keep delivery active.
- Use each panel's fullscreen button to enlarge it. Narrow windows stack the
  feeds; wide windows show them beside each other. The streams have different
  delays and are not synchronized.

Indicators and rates describe received RTP packets, not proof of every decoded
frame. Both actual camera pictures were visually checked separately. Session
data counts are video payload estimates and exclude SSH/VPN/network overhead.
Cruza's actual cellular use depends on whether it is using LTE or Wi-Fi. At the
300 kb/s configured bitrate, an additional continuous copy is approximately
135 MB/hour before overhead; pause when finished to conserve the annual SIM
allowance. Existing direct QGC video consumes its own data.

## Architecture and independence

Each original video owner still opens and encodes its camera once. GStreamer's
`multiudpsink` preserves the existing QGC destination and adds only a loopback
copy. No camera process is opened by the dashboard or its tap. There is no
dependency on the laptop in any aircraft service unit.

| Source | Original destination preserved | Local optional copy | Laptop input |
|---|---|---|---|
| Cruza IMX500, 640×480 / 15 FPS / configured 300 kb/s | 100.100.0.57:5600 | 127.0.0.1:15600 | VPN SSH to 100.100.0.58 → localhost UDP 18000 |
| quadpi IMX219, 1280×720 / 30 FPS / configured 1.5 Mb/s | 10.223.58.11:5600, with analog preview preserved | 127.0.0.1:15601 | Mesh SSH to 10.223.79.20 → localhost UDP 18002 |

The unprivileged `/opt/cruza-video-tap.py` on each Pi binds loopback only and
frames RTP onto SSH stdout. Nonblocking pipe writes discard optional packets
if the reader is slow; they cannot backpressure the encoder. Idle/stalled taps
expire. The tap has no camera, UART, MAVLink, route, reboot or modem access.
It starts only when the laptop viewer connects, not as an aircraft service.

The laptop Python app authenticates through the existing owner SSH key and
strict known-host checking; no private key is copied to either Pi. On the
Cruza VPN endpoint it verifies the same known host identity as 10.229.125.15.
MediaMTX v1.21.2 repackages H.264 RTP as WebRTC without transcoding. Browser and
media listeners bind only 127.0.0.1; no Windows firewall changes are needed.
The local HTTP app rejects foreign Host/Origin headers. Browser requests renew
a short viewing lease; stale or closed viewers lose their extra copies.
Media logs rotate at 1 MiB with two backups. No video is saved.

QGC camera destinations remain direct and do not depend on this application.
Stopping or crashing the laptop viewer cannot stop either aircraft's camera,
router, RC or FC service. Local loopback copying remains enabled on each Pi
but adds no remote traffic when the viewer is idle. Production AI observation
sharing remains disabled and independent of this video feature.

## Deployment record and rollback

Cruza backups: `/var/backups/cruza/video-dashboard-20261015T214132Z` contains
the original `cruza.py` and `config.json`. quadpi backups:
`/var/backups/quadpi/video-dashboard-20261006T163911Z` contains the original
`picam-stream.sh` and `/etc/default/picam-stream` as file `picam-stream`.
quadpi's clock was already wrong, so its backup name is not the actual date.
Deployment was on October 15. Neither clock nor FC settings were changed.

Cruza's configured `video_mirror_port` is 15600; remove it or set 0 to disable.
quadpi's `DASHBOARD_MIRROR_PORT` is 15601; set 0 to disable. After a configuration
change, restart only the corresponding video service in a suitable bench
session. Neither change requires an aircraft reboot or FC setting change.
To fully roll back, first pause/stop the laptop viewer, restore each backed-up
video script and config to its original path and restart only `cruza-video`
or `picam-stream`. The tap file can be removed after it is no longer running.
Do not restore unrelated networking, safety or flight-controller configuration.

The staged deployment scripts are guarded against overwriting code that has
changed since the audit. They are one-time deployment records; review a new
source baseline before running them again. Relevant source is in this repo's
`companion/cruza.py`, `companion/video-tap.py` and the sibling quad project's
`pi-video/picam-stream.sh`. Existing uncommitted changes were preserved.

MediaMTX was downloaded from the official v1.21.2 Windows AMD64 release; ZIP
SHA256 matched GitHub's release digest:
`a84224f5a490855684e62ba6fb71e80ea2a5e16aed61883bb58380290e93e467`.
Its existing release license is retained in `runtime/mediamtx-v1.21.2`.
`install-runtime.ps1` can reproduce that pinned download/check. Runtime files,
logs, PIDs and screenshots are ignored by Git.

## Verification and limits

- All eight companion/flight-health tests passed, including original destination
  preservation, mirror validation and use of only one camera encoder.
- Both live pictures were visible simultaneously in the browser, not inferred
  solely from packet counters. Both feeds resumed after pausing/reconnecting.
- The provided stop/start scripts were exercised successfully; the owned media
  process exited cleanly and the restarted viewer reconnected its feeds.
- Pause stopped both optional taps; original video services stayed active.
  Cruza MAVLink routing stayed active; its observation publisher stayed inactive.
- The initial video setup made no network route, firewall, radio, FC parameter,
  arming or motor changes. The fleet update later added the three laptop routes
  documented below. Each video service had one brief planned restart to enable its local
  mirror, after a fresh passive disarmed Cruza heartbeat was verified.
- quadpi reached 83.8°C with ARM-frequency capping during the bench session.
  The owner added a fan; temperature fell first to 69.3°C, then 58.5°C, and active capping
  cleared (`get_throttled=0x20000` means a historical cap remains recorded).
  Adequate cooling is still required for sustained operation; this was not a
  thermal endurance or flight acceptance test.
- Maintaining the original destinations is verified in configuration/source;
  phone QGC picture reception was not independently reconfirmed in this change.

Primary references:
[RTP ingest](https://mediamtx.org/docs/publish/rtp),
[browser playback](https://mediamtx.org/docs/read/web-browsers),
[configuration](https://mediamtx.org/docs/references/configuration-file).

## Optional fleet telemetry (15 October 2026)

The local dashboard now includes separate Cruza and quadpi telemetry cards,
mission status and a GPS position/track overview. RN03's separate aircraft is
explicitly unconfigured until its Mini is available; the wearable is only a relay.
The page uses no external map tiles and never sends flight commands or requests
missions. Full mission routes are not available from passive status messages.

`fleet.py` uses the existing `.flightlog-deps` pymavlink bundle to check frame CRCs
and decode a small telemetry allowlist. The aircraft connections remain separate,
even when both FCs use system/component ID 1/1. Unknown fields stay blank. FC
heartbeats expire after 5 seconds, positions after 3 seconds, GPS and mission
status after 10 seconds. Up to 180 track points are retained for 5 minutes in
memory. No mission-completion percentage is inferred. SSH authenticates the Pi
source; MAVLink signing is not verified by this viewer.

Each Pi has its own optional `cruza-telemetry-observer.service`, resource-limited
and independent of flight/video units. Its capture process drops to nobody and
emits only bounded telemetry to a fixed loopback UDP port. Cruza passively observes
existing outgoing QGC packets on tailscale0; if there is no outgoing pilot peer,
the dashboard waits rather than generating heartbeats or stream requests.
quadpi uses a best-effort nonblocking local copy in its existing serial bridge,
enabled by `CRUZA_FLEET_MIRROR=1`; the bridge's command-filter functions are unchanged.
The bridge was briefly restarted to enable that optional copy. Original sources
are backed up under `/var/backups/cruza-fleet-observer/` on each Pi.

The laptop reads the loopback observer through SSH without sudo. Pause affects
video only. Closing all viewers expires both laptop-copy leases after 12 seconds.
No observer is a startup dependency of the router, video or flight services.
Existing mesh observation publication remains disabled; enabling dashboard
telemetry does not enable cooperative AI observation sharing.

Disable telemetry on either Pi with:

```sh
sudo systemctl disable --now cruza-telemetry-observer.service
```

This requires no FC setting change or aircraft reboot. On quadpi, stopping the
observer leaves only harmless, nonblocking loopback sends. To remove those too,
remove `/etc/systemd/system/safety-mavlink-filter.service.d/50-fleet-observer.conf`,
run `sudo systemctl daemon-reload`, and restart `safety-mavlink-filter` at a suitable
bench maintenance time. Restore the saved bridge source if a complete rollback
is desired. Do not restart flight-related services in flight.

Validation: nine fleet decoder tests pass (CRC, source identity/isolation,
heartbeat/GPS expiry, reboot cache clearing, unknown battery/mission values and
nonfinite data). Cruza live heartbeat, disarmed/MANUAL, attitude and mission item
0 / total 10 were received. GPS had no fix, so no position was plotted. Its router
and video services stayed active. Final quadpi verification succeeded after resolving the laptop route conflict:
both camera pictures were visible together and both FC heartbeats decoded.
quadpi reported LOITER/disarmed and only heartbeat messages, so its battery,
GPS and mission fields remained unknown. Its bridge, video and observer stayed
active; temperature was 53.7 C with historical-only throttling (0x20000).
Standalone flight operation with all mesh hardware disconnected has not been
physically acceptance-tested in this dashboard change.

Browser verification confirmed that Pause video stopped optional video delivery
while Cruza heartbeat and mission status continued updating. The primary Cruza
router/video units remained active and have no observer dependency. The
`cruza-observations.service` unit remained disabled.


### Laptop VPN / mesh route collision

Tailscale advertised 10.223.0.0/16 and Windows preferred it over Alfa Wi-Fi 2.
With Windows administrator approval, `fix-mesh-routes.ps1` added three fixed,
ActiveStore (temporary) /32 routes for RN08 10.223.196.130, RN03 10.223.196.103,
and quadpi 10.223.79.20 directly through the known Alfa adapter. No default route,
Cruza LTE route, radio configuration or flight-controller setting was changed.
These routes disappear on reboot. If the overlap recurs, run this helper in an
administrator PowerShell after connecting the Alfa adapter:

```powershell
& '.\dashboard\fix-mesh-routes.ps1'
```

Remove those optional routes from an administrator PowerShell with:

```powershell
foreach ($target in @('10.223.196.130/32','10.223.196.103/32','10.223.79.20/32')) {
    Remove-NetRoute -InterfaceAlias 'Wi-Fi 2' -DestinationPrefix $target -Confirm:$false
}
```

The dashboard reconnects automatically when a source returns. The nine fleet
checks and eight existing companion/flight-health checks passed. Source changes
for quadpi's optional mirror were also retained in the sibling project's
`safety-arbiter/pi/safety_mavlink_filter.py`. Its command-policy functions were
unchanged. The original pre-copy live bridge backup is
`/var/backups/cruza-fleet-observer/bridge-20261006T170321Z/` on quadpi (its clock
was incorrect; the backup name follows that clock). Preview evidence is local
and ignored at `runtime/fleet-preview.png`.

## Geographic aircraft map (15 October 2026)

The former SVG grid is now a shared Leaflet geographic map with zoom, pan,
metric scale, fullscreen, Fit aircraft and Follow fleet controls. Each aircraft
has a separate color, permanent name label and status entry. Clicking a status
entry centers the aircraft and opens its position details. Live positions and
recent tracks update passively. A dashed gray marker explicitly shows a
last-known position; it expires with the existing 5-minute track retention.
No GPS fix, offline telemetry and an unconfigured Mini remain distinct states.
There is no estimated position or substituted laptop/radio position.

By default the map loads local, low-detail Natural Earth country outlines and
makes no external map requests. Detailed streets are optional: clicking **Enable
street map** requests visible tiles from OpenStreetMap and reveals the viewed
area and public IP to that service. This choice resets to the offline overview
on page reload. Ordinary browser tile caching is retained, attribution is visible,
and no tile prefetch or offline tile download is implemented. When internet is
unavailable, select **Use offline overview**; markers and tracks continue using
the local telemetry. The country outline layer has no street-level detail.

All map code and data are served by the existing loopback dashboard. No aircraft
configuration, FC parameter, stream rate or pilot route was changed for mapping.
On this bench, Cruza reports GPS fix 0 / 0 satellites, while quadpi sends heartbeat
telemetry without positions. Their real markers will appear when the existing
pilot telemetry supplies valid GPS data. Physical outdoor GPS-lock validation
was not performed. Neither aircraft was placed on the map using guessed data.

Verification: nine fleet decoder tests and ten JS map-state assertions passed.
A separate localhost test page, explicitly labeled SIMULATED, verified two live
markers, one last-known marker, trail display, aircraft focus, expiry/removal and
successful street tile loading. That test page/server were removed afterward.
The live dashboard retained its real telemetry, video and empty-GPS state.

Vendored map assets:

- Leaflet 1.9.4 from its [official download instructions](https://leafletjs.com/download.html),
  BSD-2-Clause license retained at `dist/leaflet-LICENSE.txt`. Both JS and CSS
  SHA256 were verified against the official published SRI hashes.
- `dist/world.geojson`: Natural Earth 1:110m countries from the
  [upstream repository](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson),
  public-domain geographic data. SHA256:
  `6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`.
- Optional online tiles follow the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

Run map state checks with `node dashboard/test_map.cjs` from the workspace root.

The laptop telemetry reader now has a separate 15-second SSH viewer lease, using
`companion/telemetry-session.py`. If the viewer/transport disappears, the wrapper
terminates only its optional loopback reader (and kills that child if necessary).
This prevents a stale reader holding the observer port after a lost connection.
Lease messages terminate at this wrapper and never reach MAVLink or any flight
service. Four cleanup/port restriction tests pass. The map changes did not
restart an aircraft service.
The final reconnect check stopped only the laptop viewer, waited 17 seconds,
and confirmed quadpi's optional reader port was released while its bridge,
video and observer services remained active. Restarting the laptop dashboard
restored its independent telemetry/video copies.

### Simultaneous map and camera layout

The default dashboard now places the shared map alongside both camera panels
on wide screens. On narrow screens the map is compact and the two camera panels
share a row, with aircraft status in expandable sections. **Expand dashboard**
expands the entire combined view, preserving both map and video. The former
map-only fullscreen action was replaced. This is a layout-only change; camera
and telemetry transports are unchanged.

### Fresh-checkout Python dependency

From the Cruza repository root, install the tested telemetry decoder into the
ignored dependency directory before first launch (or provide it in your Python
environment):

```powershell
$dashboardPython = "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
& $dashboardPython -m pip install --target .flightlog-deps -r dashboard/requirements.txt
& ./dashboard/install-runtime.ps1
& ./dashboard/start-dashboard.ps1 -PythonPath $dashboardPython
```

The dashboard uses the existing SSH identity and strict known-host verification;
keys and runtime configuration are not bundled. The deployment scripts are
bench-specific, guarded migrations for the audited Pi versions, not universal
installers; they deliberately refuse changed source hashes.

### U.S. state boundaries (16 October 2026)

The offline map now includes all 50 U.S. states and Washington, DC, with state
borders, zoom-dependent postal labels and full state names on hover. Initial
framing and **U.S. overview** show the contiguous U.S.; Alaska and Hawaii are
included and can be reached by panning/zooming. This basemap framing is not an
inferred aircraft position. Fit/follow still uses only real telemetry. State
borders remain visible over optional street tiles. Both live camera panels stay
in the combined layout.

`dist/us-states.geojson` retains only USA geometry, names, postal codes and label
coordinates from the public-domain Natural Earth 1:110m
[states/provinces dataset](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_1_states_provinces.geojson).
Its 51 unique features were checked, including numeric label coordinates; SHA256
`6c31b8f35e04a8a2ea808e1aa245c37134e8c7fe161db9329e8b93afcd2b9eca`.
The dataset is an overview, with generalized boundaries. It is served locally
and adds no external map requests. The laptop viewer was restarted to serve the
new asset; no aircraft service was changed or restarted.

### Alabama counties, places and major roads (16 October 2026)

**Alabama** frames the state while retaining both camera panels. Local layers
load once when the state enters view at zoom 5 or closer. County borders, major
cities and interstates start at zoom 6; U.S. highways at 7; county names and
regional cities at 8; state highways at 9; smaller incorporated places at 10;
and other Census places at 12. Interstate route badges start at 7, U.S. route
badges at 9 and state route badges at 11. Labels compete for space by priority,
so not every name is printed simultaneously; city dots and hover names retain
access to the place names. Counties, Cities and Highways switches independently
show/hide their layers. Boundary and road geometry are generalized for display.

The bundled data contain 67 counties, 594 incorporated/Census places, and 373
named interstate, U.S. and state-highway route groups. Major city labels are a
fixed display-priority list, not a population ranking. Place locations use points
inside their Census boundaries, not estimates of aircraft positions. Highway
geometry is grouped by route name/type, simplified and drawn on a canvas below
aircraft markers. Only visible labels are laid out; overlapping names are
suppressed. No flight, radio, camera or observer settings were changed.

Sources are the U.S. Census Bureau TIGERweb county query, 2024 Alabama 1:500k
cartographic places, and 2025 Alabama primary/secondary roads. Exact URLs,
feature counts, retrieval date and output hashes are in
`alabama-data-sources.json`. Census attribution is visible on the map. These
layers use only local files, even when internet or optional street tiles are
unavailable. Roads are static map data; local residential streets remain
available through the optional street-map layer.

To rebuild, put the source files at `runtime/al-counties-source.geojson`,
`runtime/al-places.zip`, and `runtime/al-roads.zip`. The build tool uses pyshp
3.1.6, Shapely 2.2.0 from `runtime/map-build-deps/` and the project's existing
NumPy 2.5.3 in `.flightlog-deps/`. Run `python dashboard/build-alabama-data.py`.
These packages are build-only; normal viewing requires no GIS package.

Validation: dataset checks verify all 67 unique Alabama county IDs, city coverage
and major interstate routes. Browser checks verified county/city/route labels at
closer zoom, removal of county lines/names independently of roads, and deeper
zoom detail. Camera panels remain in the combined layout. Restarting the laptop
viewer to add static assets did not restart an aircraft service.

## Alerts, extra readings and graphs (18 October 2026)

A banner under the page header lists every active alert across the fleet,
critical first (red, ⛔) then warnings (amber, ⚠). Each aircraft card repeats
its own alerts above the video and highlights the affected reading. Labels and
icons accompany the colors, so state is never shown by color alone.

**Sound alerts** is off when the page opens, because browsers only allow sound
after a click. Turn it on once per session. A new warning beeps once; a critical
alert beeps three tones every 10 seconds until **Silence these alerts** is
pressed. Silencing lasts until that alert clears; a new message or an escalation
to critical sounds again.

Alert rules (all computed on the laptop from passive telemetry):

| Alert | Level | Rule |
|---|---|---|
| Telemetry lost | critical if last seen ARMED, else warning | No FC heartbeat for 5 s |
| Battery low / critical | warning / critical | Voltage below the limit for 5 s straight (brief throttle sag ignored) |
| No 3D GPS fix | critical | Only while armed |
| Few satellites | warning | Fewer than 6 while armed |
| RC receiver signal lost | critical if armed | Flight controller reports the RC receiver unhealthy |
| Sensor unhealthy | warning (attitude estimate: critical if armed) | Flight controller health flags |
| Airspeed below minimum | warning | Armed, airborne, under the minimum for 5 s |
| Aircraft messages | ArduPilot error/critical → critical 60 s; warning → warning 30 s | Text the autopilot sends to QGC |

Cruza's limits copy its flight-controller settings in the 2026-10-14 snapshot:
BATT_LOW_VOLT 14.0 V, BATT_CRT_VOLT 13.2 V and AIRSPEED_MIN 10 m/s. They are
the `LIMITS` table near the top of `server.py`; change them there if those
parameters change. quadpi's battery limits are unknown, so its battery and
airspeed checks are off. The dashboard only warns; the aircraft's own failsafes
are unchanged and remain the actual protection.

New readings on each card: airspeed, heading, climb rate, throttle, distance and
direction from home (from HOME_POSITION, or the first armed GPS position when
home has not been seen), landed state, pre-arm status and sensor health. Two
five-minute graphs show altitude and airspeed; hover a graph for a value. A
**Messages** list keeps the last 30 events: arm/disarm, mode changes, telemetry
loss/restoration and the autopilot's text messages, with repeats collapsed
(×N). The map shows a heading arrow on live aircraft, and its popup adds
airspeed and distance from home. History is in memory only and clears when the
dashboard or the Pi observer restarts.

### Pi observer update required for autopilot messages

The autopilot's text messages (STATUSTEXT) and home position (HOME_POSITION)
only reach the laptop after the updated `companion/telemetry-tap.py` is
installed on each Pi. Until then everything else above works, but the
Messages list shows only laptop-detected events and distance uses the launch
point. The updated observer forwards those two extra message types, passes
every text message rather than thinning them to one per half second, and caps
text at 20 messages per 10 s. It still only watches outgoing packets and cannot
send anything. Install it with the existing guarded installer, which backs up
the current files and restarts only the optional observer service:

```sh
sudo ./install-telemetry-observer.sh cruza    # on Cruza, from a copy of companion/
sudo ./install-telemetry-observer.sh quadpi   # on quadpi
```

Validation: 22 fleet decoder/session tests pass, including text messages and
chunk joining, repeat collapsing, arm/mode events, lost-link escalation, the
5-second battery rule (and that a brief sag does not alert), RC loss, distance
from home and graph history. A local, explicitly SIMULATED harness (not in the
repository) served the real page with a circling Cruza and an armed quadpi that
lost its link; desktop and phone-width screenshots, graph hover, sound toggle
and silencing were checked with no page errors. Not yet checked against live
aircraft.
