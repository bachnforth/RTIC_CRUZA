# Five-minute airspeed calibration mission — 2026-10-13

Created `Cruza_Airspeed_Calibration_5min_60m_2026-10-13.plan` in both the workspace `missions/` directory and `C:/Users/ebach/Documents/QGroundControl/Missions/`. The plan is a file for loading and reviewing in QGC; it has not been loaded in the application, uploaded, or flight-tested. No aircraft parameters were changed.

## Route

Reconstructed the most recent flown mission from log 14's CMD records, rather than relying on the older draft's different launch and first waypoints. Retained the recorded takeoff, all navigation points, landing approach altitudes, and LAND command parameters. Added a single timed loiter between the old waypoint 5 and waypoint 6; later items are renumbered.

| QGC item | Action | Relative altitude |
|---|---|---:|
| 1 | Existing takeoff, 10-degree pitch parameter | 60 m |
| 2–5 | Existing outbound circuit waypoints | 60 m |
| 6 | Clockwise timed loiter, 300 seconds | 60 m |
| 7 | Existing northern waypoint (previous item 6) | 60 m |
| 8 | Existing approach setup (previous item 7) | 36 m |
| 9 | Existing approach setup (previous item 8) | 16 m |
| 10 | Existing LAND point | 0 m |

Loiter center: **33.7244733115942, -85.91135246262625**, near the northwest end of the previous pattern. Nominal radius: **60 m**, matching the current `WP_LOITER_RAD`. The nominal circle lies inside the previous mission's waypoint outline. That outline is not a surveyed boundary or obstacle-clearance assessment, and actual flight entry/exit and radius vary with navigation guidance, speed, and wind. Review the circle's location and clearance on the QGC map before uploading.

The mission uses `MAV_CMD_NAV_LOITER_TIME` (19), with time 300 seconds and tangent exit selected. ArduPlane 4.7.1 starts the timer after reaching the loiter target, then exits toward the next waypoint after the timer and heading conditions are met. For this command, Plane uses `WP_LOITER_RAD`; it does not use the magnitude of the mission item's radius field. The plan has a positive 60 in that field for clockwise direction and consistency with the nominal preview. [ArduPilot mission commands](https://ardupilot.org/plane/docs/common-mavlink-mission-command-messages-mav_cmd.html), [exact 4.7.1 handler](https://raw.githubusercontent.com/ArduPilot/ardupilot/Plane-4.7.1/ArduPlane/commands_logic.cpp).

The previous flight lasted about two minutes. Adding a full five-minute orbit gives an estimated total flight of about **7–8 minutes**, allowing for entry and exit. Timing is not dependent on repeating a guessed number of circuit laps. At a nominal 16.5 m/s and 60 m radius, still-air orbit time is about 23 seconds, providing roughly 13 revolutions over five minutes; this is an illustration, not a predicted exact flight path.

## Loading and settings

Open QGC's Plan view, use its Open/Load-from-file control, and select the new plan in the normal Missions folder. Check item 6 is a timed loiter for **300 seconds at 60 m relative altitude**, and review the entire map and approach before uploading. Only file syntax/contents and firmware command semantics were validated here; QGC loading and an onboard mission readback remain pending.

Before calibration, confirm:

- `ARSPD_AUTOCAL=1`, `ARSPD_USE=0`, `ARSPD_SKIP_CAL=0`.
- `WP_LOITER_RAD=60`. The last full snapshot already has this value; no radius parameter change is required for this plan.
- Correct startup zeroing with the pitot loosely shielded, then removal of its cover before flight.
- Adequate endurance and usable voltage monitoring for the longer flight. The logged current monitor remains invalid for propulsion consumption/remaining-capacity estimates.

The QGC planning cruise speed is 15 m/s to match the owner's selected cruise setting. This is planning metadata, not a DO_CHANGE_SPEED command or assurance of 15 m/s sensor-controlled flight while `ARSPD_USE=0`.

After landing, set `ARSPD_AUTOCAL=0` and export parameters before power cycling, then retrieve/review the new log. Leave `ARSPD_USE=0` until ratio convergence and suitable speed targets are reviewed.

## Validation and artifacts

- Valid JSON QGC Plan v1 with fixed-wing ArduPilot mission v2 and 10 SimpleItems, sequential IDs 1–10, seven MAVLink parameters each, relative-altitude frames, finite coordinates.
- Every original mission item matches log 14's recorded command and parameters exactly; the only new command is the timed loiter.
- Workspace and QGC-folder plan copies are byte-identical. Nominal circle geometric containment checked against previous waypoint outline.
- Reproducible builder: `tools/create-calibration-mission.py`.
- [Route preview](../missions/Cruza_Airspeed_Calibration_5min_60m_2026-10-13.png).
