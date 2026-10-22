# Flight log retrieval and comparison

After landing, disarm the Cruza and connect its flight controller to the computer by USB. Tell the assistant the new flight is ready for review, including launch mode, wind, battery, observed behavior, and any settings or hardware changes. The assistant can then retrieve and analyze the new onboard DataFlash logs. This requires the aircraft to be connected; no automatic monitor has been scheduled.

## Retrieval tools

Install the Python dependencies into the local ignored directory if they are not already present:

```powershell
python -m pip install --target .flightlog-deps -r tools/flightlog-requirements.txt
```

Use the Python executable configured for this workspace. The USB MAVLink port is currently COM17; confirm it on each connection. A ground station must release the serial port if it is already using it.

```powershell
python tools/pull-flight-logs.py --port COM17 --count 3
python tools/analyze-flight-log.py logs/<date>/<download-session>/log_<id>.BIN
```

The retrieval script refuses an armed vehicle and sends only firmware/parameter/log requests. It does not erase logs, change parameters, arm, change flight mode, or run motors. Every default retrieval gets a new timestamped directory and parameter snapshot so an additional flight on the same day cannot overwrite the previous baseline. The onboard log index, reported sizes, downloaded files, and printed SHA-256 values support archive integrity checking.

The analyzer generates a plot, summary, and full parsed records beside each BIN. Keep original BIN files, plots, and summaries in Git. Full `.records.json` files and installed dependencies stay local because they can be regenerated.

`update-cruise-throttle.py` and `esc-calibration-bench.py` document the attended 2026-10-09 changes; they are parameter-writing tools, not part of log retrieval or ordinary flight preparation. Do not rerun them as a preflight step. ESC calibration backup files now show restoration complete.

## Baseline and next report

Use `logs/2026-10-09/log_00009.BIN` as the first successful AUTO circuit baseline, with findings in `docs/flight-review-2026-10-09.md`. The next flight differs in two recorded ways: TRIM_THROTTLE increased from 45 to 54, and both original ESCs underwent 1100–1900 µs endpoint calibration followed by an owner-confirmed smooth props-off startup test. Controller parameters after restoration and reboot are in `params/cruza_params_2026-10-09_post_esc_calibration.params`.

The subsequent test is log 12 in `logs/2026-10-09/download-110522_067346/`; see `docs/flight-review-2026-10-09-second-flight.md`. Use it as the baseline for future tests with trim 54 and calibrated ESCs, retaining log 9 for the original comparison. Generate comparisons and plots after analyzing both logs:

```powershell
python tools/compare-flight-logs.py <baseline.BIN> <new-flight.BIN> <comparison.json>
python tools/plot-flight-comparison.py <comparison.json>
```

The comparison tool expects completed AUTO takeoff and mission-5/mission-6 messages in both logs. For a different mission or flight mode, select and analyze suitable phases explicitly instead of using that assumption.

The next report should compare launch acceleration/initial height loss, time to the mission takeoff altitude, throttle output, altitude tracking, groundspeed, pitch/roll demand versus response, GPS/estimator/vibration health, and approach/landing behavior. Identify the actual airborne log rather than assuming the newest log is the flight. Separate takeoff, level cruise, turns, descent, and ground activity. Confirm any parameter differences using the flight's PARM records and a new live snapshot.

The confirmed battery is 4S / 14.8 V; the kit motors, props, and original external ESCs are retained. Manufacturer stock propulsion documentation recommends 6S, but increased voltage has not been prescribed or tested on this modified build. There is no enabled airspeed sensor: GPS groundspeed must not be presented as measured airspeed. The low current readings may represent only electronics if external ESC power bypasses the AIO's sensor; do not derive propulsion power or useful battery capacity from them until wiring is verified.

Record flight conditions alongside the comparison: wind, battery charge, launch technique, mass/CG, and mission/settings changes can affect the result. ESC acceptance tones and smooth startup do not alone quantify an increase in takeoff thrust.
