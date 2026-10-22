# Link test installation — 22 October 2026

## Follow-up after administrator route approval

Cruza now has RouteAll=true. Its route to 10.223.79.20 uses tailscale0,
and its peer map assigns 10.223.79.20/32 to alien08 (100.100.0.23).
Cruza's Tailscale ping to that destination reaches alien08 in 117 ms.
The laptop reaches QuadPi directly over mesh (two pings, 5 ms each).

The remaining demonstrated blocker is alien08's VPN packet filter. Its compiled
rules permit Cruza traffic to alien08's own VPN address but do not permit Cruza
traffic addressed to QuadPi's mesh address. During one mesh-only preflight,
`tstun_in_from_wg_drop_filter` increased from 26 to 39: exactly 13 drops for the
three hello packets and ten probes. A bounded raw packet capture on QuadPi
observed no test UDP traffic during a separate mesh-only preflight.

Required administrator policy addition: allow UDP source 100.100.0.58 to
destination 10.223.79.20, destination port 15700, through alien08. Preserve
existing policy. Route approval alone does not grant this traffic permission.
Then repeat packet capture, delivery and return-path checks.

Also fixed the test's gateway display to select the longest matching subnet
prefix; it previously displayed alien03's /16 despite alien08's active /32.

Source: origin/cruza-quad-link-test, commit 62f90e6.
The existing checkout stays on dashboard-field-imagery; linktest files are local,
uncommitted additions. No changes were written to TFWdrone.

## Installed

- tfwcruza, ebach@100.100.0.58: ~/linktest/linktest.py and plan.json.
- QuadPi, accessed as ebach@10.223.79.20: same runtime and plan. report.py and
  test_linktest.py were also copied for validation.
- Each Pi uses ~/linktest-logs. These are manually started tools, not boot services.
- Both VPN and mesh destinations are enabled for QuadPi and TFWdrone.
- Each echo binds its VPN and mesh addresses separately, preserving reply source.
- The laptop runner uses the existing id_ed25519_rpi key and trusted host aliases.
- The report reader now finds metadata after an initial low-disk note.
- Laptop reporting uses the available bundled Python; flight-log dependencies
  already exist in .flightlog-deps.

## Ground verification

Cruza had LTE connected and Wi-Fi down. QuadPi had Wi-Fi and mesh connected.
QuadPi logged all ten probes from the initial preflight, while Cruza received
insufficient replies to pass. A subsequent 15-second VPN session sent 76 probes;
the collected receiver logs confirm 98.7% delivery, but RTT95 was 3,284 ms,
exceeding the 1,000 ms target. The short ground check does not establish flight
performance. The laptop successfully generated the HTML/CSV report. This proves
application traffic can arrive, not that the VPN path is reliable enough.
Eight focused unit checks passed on QuadPi. The full integration check reached
report generation but QuadPi lacks matplotlib; reporting belongs on the laptop.
Temporary test processes were stopped after verification.

## Mesh routing still required

Ask the VPN administrator to approve the advertised route 10.223.79.20/32
through alien08 (100.100.0.23), preserving any existing approved routes, and
permit Cruza (100.100.0.58) to reach QuadPi UDP 15700 through that subnet route.
The approved route currently visible is 10.223.0.0/16 through alien03/skipperpi;
alien08's specific host route was not visible as approved.

On Cruza, an authenticated administrator must also run:

```sh
sudo tailscale set --accept-routes=true
```

Cruza currently has RouteAll=false; ebach cannot change it without sudo
authentication. No routing preference was changed during installation.
After both steps, inspect accepted routes and confirm 10.223.79.20 selects the
alien08 /32. Check the gateway's forwarding/firewall, source translation and
QuadPi's reply route with observed packets. Current QuadPi replies to Cruza's
VPN address select tailscale0; a mesh destination alone does not prove that
both directions traversed the mesh. Configure a narrow return route or exact
gateway source allowance only if demonstrated necessary. Do not call mesh
accepted until packet delivery and the actual forward/return paths are verified.

The alien08 /32 applies to QuadPi only. TFWdrone's mesh address 10.223.53.30
needs its own working/approved gateway path; enabling its target is not proof.

## Partner installation

Copy linktest.py and plan.json to ~/linktest on TFWdrone. Then run:

```sh
mkdir -p ~/linktest-logs
cd ~/linktest
nohup python3 linktest.py echo --name tfwdrone > ~/linktest-logs/echo-console.log 2>&1 < /dev/null &
```

Configured addresses are VPN 100.100.0.6 and mesh 10.223.53.30. Verify both are
assigned on that Pi before starting, since the echo binds them explicitly.
After testing, stop with `python3 ~/linktest/linktest.py stop --role echo`
and provide the session directories under ~/linktest-logs to the report operator.

## Commands from this laptop

```powershell
.\linktest\run-linktest.ps1 start -Quad quadpi
.\linktest\run-linktest.ps1 watch
.\linktest\run-linktest.ps1 stop -Quad quadpi
.\linktest\run-linktest.ps1 collect -Quad quadpi
```

Without -Quad, both quads are test targets. TFWdrone is skipped for remote
installation/start/collection, and its echo must be managed by the partner.
Preflight failure blocks the sender; do not bypass a missing mesh route with -Force.
