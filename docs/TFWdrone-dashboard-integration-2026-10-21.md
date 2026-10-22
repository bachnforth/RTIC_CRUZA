# TFWdrone dashboard integration — October 21, 2026

Fetched `origin/lte-bvlos-flight-review` through partner commit
`91ee49bcb33b9019b97160145bc8cbe71f2ba49f` (per-source SSH username).
The RN03 TCP reader was introduced by `22439ab7d11ef45a0d64c1397bc33e569788b502`.
The only open GitHub PR found was dashboard-alerts #1, which did not contain
these new partner changes.

Adapted the partner's `split_frames` / `DirectTelemetry` implementation into
the current working dashboard while retaining the local alerts, map, imagery,
and TFW drone card changes. The active source is `rn03`, using TFWdrone's
VPN address `100.100.0.6`, TCP port `5760`. It receives only; no MAVLink
application bytes are transmitted. CRC and FC identity checks remain active.
The SSH source class retains the partner's per-source username support, but
TFW drone currently uses TCP instead of SSH. Its FC identity is system 1,
component 1. The sources remain separate despite matching FC IDs.

This was a targeted working-tree integration, not a full branch merge or a
push. Unrelated flight-review commits and existing local edits were preserved.
Pre-integration snapshots and the complete tracked working diff are saved in
`dashboard/runtime/tfw-import-20261021-144732/`.

Live verification: fresh heartbeat, STABILIZE, disarmed, GPS fix type 4 with
28 satellites, position populated, battery approximately 16.62 V. These are
point-in-time observations, not a flight-readiness assessment. Twenty-nine
Python tests and the map checks passed. Added regression checks cover stream
fragmentation, signed/v1 lengths, receive-only operation and EOF socket cleanup.

The incoming UDP video implementation binds the pilot's existing destination
port with SO_REUSEADDR and can take packets from QGC. It was not activated.
It also assumes another laptop's mesh address (`10.223.53.10`), unlike this
laptop (`10.223.58.11`). TFW drone video remains explicitly unconfigured;
a separate optional mirror/feed is needed. No aircraft service, FC setting,
route or QGC connection was changed during this integration.
