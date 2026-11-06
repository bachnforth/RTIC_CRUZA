#!/usr/bin/env python3
"""Measure each camera's mount angles and field of view against a known point.

Why this exists: swarm.py turns a detection's angles off the camera boresight
into a point on the ground, and it can only do that by trusting four numbers per
airframe - mount yaw, mount pitch-down, and the horizontal and vertical field of
view. The bench sweep says a 1-degree pitch-down error moves the Cruza's point 65
metres at the Cruza's ~309 m working range, and 10 degrees moves it 348 m, far
enough that two aircraft stop agreeing they are looking at one object. So these
four numbers are the whole accuracy of the shared picture.

The method needs no optimiser. Put something the detector recognises at a
surveyed point, record what each camera reports while the aircraft's own
telemetry is logged, and every single observation gives a direct estimate:

    the observer reports   az_rel = bearing_to_target - heading - yaw
                           el_rel = pitch_down - pitch - depression

    so each record says    yaw        = bearing - heading - az_rel
                           pitch_down = el_rel + pitch + depression

Average those and the spread is your uncertainty, honestly come by. No fitting,
nothing to converge, and a bad truth point or noisy telemetry shows up as a wide
spread instead of a confident wrong answer.

Two cautions this tool reports on rather than hiding:

- Mount yaw and a compass bias are the same number if every observation is taken
  on one heading. Observe the point from headings at least 90 degrees apart and
  they separate; until then, what you measured is "yaw plus whatever the compass
  is doing", which is still the right thing to put in SENSORS for that heading.
- A field-of-view error scales az_rel and el_rel, so it corrupts the mount
  estimate unless the target sits near the frame centre. Calibrate the mount
  with the target centred, then calibrate the field of view with targets out at
  the frame edges, where the scaling is what you are trying to see.

Modes:
  solve    mount yaw and pitch-down from records + truth (+ a flight log, or a
           static aircraft state given on the command line)
  fov      horizontal/vertical field of view from off-centre observations
  check    what a camera should report for a setup you are about to build, so
           you can lay out a ground calibration with a tape measure
  capture  run on an aircraft's Pi: log every observer record with a timestamp

Nothing here opens a serial port, speaks MAVLink or writes to an aircraft.
capture binds one loopback UDP port read-only; the rest reads files.
"""
import argparse
import json
import math
import socket
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'dashboard'))
import swarm                                   # noqa: E402
from swarmtest import wrap180, vehicle_state   # noqa: E402

GPS_EPOCH_UNIX = 315964800   # 1980-01-06 00:00:00 UTC
GPS_UTC_LEAP_S = 18          # GPS - UTC, constant since 2017
MATCH_TOLERANCE_S = 1.0      # how close a record must be to a log sample
CENTRED_DEG = 8.0            # beyond this off-centre, FOV error pollutes a mount fit
EDGE_FRACTION = 0.25         # a useful FOV sample sits at least this far off centre
MIN_CAMERA_HEIGHT_M = 0.5    # below this the depression is noise, even on a tripod

# The detector reports the centre of its bounding box, and swarm.py places that
# point on the ground. For a standing person the box spans head to feet, so its
# centre is about half their height up - and that offset wrecks a close-range
# ground calibration while meaning nothing in flight. Camera 1.2 m up with the
# marker 4.5 m out: a 0.85 m box centre makes the depression 4.5 deg instead of
# 14.9, so pitch_down comes out 10.5 deg wrong. The same 0.85 m at 100 m over a
# 309 m slant shifts it 0.14 deg. So target_height matters on the ground and
# is safely ignored in the air, and it is the caller's job to say what it is.


# --------------------------------------------------------------------------
# Flight log -> absolute time, position and attitude
# --------------------------------------------------------------------------

def gps_unix(week, ms):
    return GPS_EPOCH_UNIX+week*604800+ms/1000.0-GPS_UTC_LEAP_S


def log_states(path, ground_alt=None):
    """Samples of (unix_time, lat, lon, agl, heading, pitch) from a flight log.

    The log timestamps everything in microseconds since boot, so absolute time
    comes from the GPS records' week and millisecond fields. Attitude is matched
    to each position by log time, because the two streams are logged
    independently.

    Height above ground is taken as GPS altitude minus the lowest altitude in
    the log, which is right for a log that starts and ends on the ground - the
    normal case - and wrong for one that begins already airborne, where it will
    read every sample as too low. Pass ground_alt (metres above sea level at the
    launch point) when that applies; the whole pitch calibration scales with
    this number, so it is worth being sure of.
    """
    data = json.loads(Path(path).read_text())
    gps = [g for g in data.get('GPS', [])
           if g.get('Status', 0) >= 3 and g.get('GWk') and g.get('Lat')]
    if not gps:
        raise SystemExit(f'{path}: no 3D-fix GPS records with GPS week')
    att = sorted(((a.get('TimeUS', 0), a.get('Pitch', 0.0), a.get('Yaw'))
                  for a in data.get('ATT', [])), key=lambda r: r[0])
    ground = min(g.get('Alt', 0.0) for g in gps) if ground_alt is None else ground_alt
    spread = max(g.get('Alt', 0.0) for g in gps)-ground
    if ground_alt is None and spread < 10:
        print(f'  ! {path}: altitude only spans {spread:.1f} m, so the log may '
              f'not contain the launch point. Height above ground is being '
              f'measured from {ground:.1f} m AMSL. Pass --ground-alt if that '
              f'is wrong - the pitch result depends on it.', file=sys.stderr)
    states = []
    for g in gps:
        unix = gps_unix(g['GWk'], g['GMS'])
        pitch, yaw = 0.0, g.get('GCrs', 0.0)
        if att:
            i = min(range(len(att)), key=lambda k: abs(att[k][0]-g.get('TimeUS', 0)))
            pitch = att[i][1] or 0.0
            if att[i][2] is not None:
                yaw = att[i][2]
        states.append((unix, g['Lat'], g['Lng'], g.get('Alt', 0.0)-ground,
                       yaw % 360, pitch))
    states.sort()
    return states


def nearest_state(states, when, tolerance=MATCH_TOLERANCE_S):
    """The log sample closest in time, or None if nothing is close enough."""
    if not states:
        return None
    best = min(states, key=lambda s: abs(s[0]-when))
    return best if abs(best[0]-when) <= tolerance else None


# --------------------------------------------------------------------------
# The measurement itself
# --------------------------------------------------------------------------

def tape_estimate(record, height, distance, offset=0.0, pitch=0.0,
                  target_height=0.0):
    """One estimate from a geometry measured with a tape, not a GPS.

    For a static calibration this is strictly better than two GPS fixes. A
    ground baseline is a few metres long and a handheld fix is good to three or
    five, so the bearing between two such fixes is close to meaningless, while a
    tape gives centimetres. It also takes the compass out of the yaw
    measurement: sight the nose at the marker, leave offset at zero, and the
    reported azimuth *is* the mount yaw with the sign flipped.

    height         lens centre above the ground, metres
    distance       horizontal lens-to-marker, metres, along the nose
    offset         how far the marker sits to the RIGHT of the nose line, metres
    target_height  height of the DETECTION BOX CENTRE above the ground - about
                   half a standing person's height, not their full height
    """
    if distance <= 0 or height <= MIN_CAMERA_HEIGHT_M:
        return None
    effective = height-target_height
    if effective <= 0:
        return None
    ground_range = math.hypot(distance, offset)
    depression = math.degrees(math.atan2(effective, ground_range))
    if not swarm.MIN_DEPRESSION_DEG <= depression <= swarm.MAX_DEPRESSION_DEG:
        return None
    # Bearing to the marker relative to the nose, from the tape alone.
    az_true = math.degrees(math.atan2(offset, distance))
    az_rel, el_rel = record['az_rel_deg'], record['el_rel_deg']
    return {'t': record.get('t'), 'cls': record.get('cls'),
            'score': record.get('score'),
            'az_rel_deg': az_rel, 'el_rel_deg': el_rel,
            'ground_range_m': ground_range, 'agl_m': height,
            'target_height_m': target_height, 'effective_height_m': effective,
            'heading_deg': 0.0, 'pitch_deg': pitch,
            'bearing_deg': az_true, 'depression_deg': depression,
            'yaw_est': wrap180(az_true-az_rel),
            'pitch_down_est': el_rel+pitch+depression,
            'centred': abs(az_rel) <= CENTRED_DEG and abs(el_rel) <= CENTRED_DEG}


def estimate(record, state, truth, target_height=0.0):
    """One record + one aircraft state + the truth point -> one estimate.

    state is (unix, lat, lon, agl, heading, pitch). Returns the mount angles
    this single observation implies, plus the geometry it came from, so a bad
    sample can be recognised rather than averaged in silently.

    Returns None for a geometry that cannot inform a calibration. This matters
    more than it looks: a record whose timestamp lands on a log sample taken
    while the aircraft was still on the ground has a depression near zero, and
    averaging it in drags the pitch estimate a long way without looking wrong.
    The accepted band is the one swarm.py will actually range in, so a sample it
    rejects is no use for predicting what it will do.
    """
    _, lat, lon, agl, heading, pitch = state
    ground_range, bearing = swarm.distance_bearing(lat, lon, truth['lat'], truth['lon'])
    if ground_range < 1.0 or agl <= MIN_CAMERA_HEIGHT_M:
        return None
    effective = agl-target_height
    if effective <= 0:
        return None
    depression = math.degrees(math.atan2(effective, ground_range))
    if not swarm.MIN_DEPRESSION_DEG <= depression <= swarm.MAX_DEPRESSION_DEG:
        return None
    az_rel = record['az_rel_deg']
    el_rel = record['el_rel_deg']
    return {'t': record.get('t'), 'cls': record.get('cls'),
            'score': record.get('score'),
            'az_rel_deg': az_rel, 'el_rel_deg': el_rel,
            'ground_range_m': ground_range, 'agl_m': agl,
            'target_height_m': target_height, 'effective_height_m': effective,
            'heading_deg': heading, 'pitch_deg': pitch,
            'bearing_deg': bearing, 'depression_deg': depression,
            'yaw_est': wrap180(bearing-heading-az_rel),
            'pitch_down_est': el_rel+pitch+depression,
            'centred': abs(az_rel) <= CENTRED_DEG and abs(el_rel) <= CENTRED_DEG}


def summarise(values):
    """Mean, spread and range of a set of single-observation estimates."""
    if not values:
        return None
    mean = statistics.fmean(values)
    return {'mean': mean, 'n': len(values),
            'stdev': statistics.stdev(values) if len(values) > 1 else 0.0,
            'min': min(values), 'max': max(values),
            'median': statistics.median(values)}


def metres_at(angle_deg, range_m):
    """What an angular error costs in metres of ground error at a given range."""
    return range_m*math.radians(angle_deg)


def load_records(path, cls=None, min_score=0.0):
    """Observer records from a capture file: one JSON object per line."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or 'az_rel_deg' not in record:
            continue
        if cls and str(record.get('cls', '')).lower() != cls.lower():
            continue
        if float(record.get('score', 0)) < min_score:
            continue
        out.append(record)
    return out


def solve(args):
    records = load_records(args.records, args.cls, args.min_score)
    if not records:
        raise SystemExit(f'{args.records}: no usable records '
                         f'(class filter {args.cls!r}, min score {args.min_score})')
    tape = args.height is not None or args.distance is not None
    truth = None
    states = None
    if tape:
        if args.height is None or args.distance is None:
            raise SystemExit('A tape geometry needs both --height and --distance')
    elif args.lat is None or args.lon is None:
        raise SystemExit('Give the truth point with --lat/--lon, or a measured '
                         'ground geometry with --height/--distance')
    else:
        truth = {'lat': args.lat, 'lon': args.lon}
    if tape:
        print(f'Tape geometry: lens {args.height:.2f} m up, marker '
              f'{args.distance:.2f} m out'
              + (f', {args.offset:+.2f} m right' if args.offset
                 else ' on the nose line')
              + f', box centre {args.target_height:.2f} m up'
              + f' -> {args.height-args.target_height:.2f} m of working height')
    elif args.log:
        states = log_states(args.log, args.ground_alt)
        print(f'{len(states)} log samples spanning '
              f'{states[-1][0]-states[0][0]:.0f} s')
    else:
        for name in ('aircraft_lat', 'aircraft_lon', 'agl', 'heading'):
            if getattr(args, name) is None:
                raise SystemExit('Without --log or a tape geometry, give '
                                 '--aircraft-lat, --aircraft-lon, --agl and '
                                 '--heading')

    estimates, unmatched, rejected = [], 0, 0
    for record in records:
        if tape:
            single = tape_estimate(record, args.height, args.distance,
                                   args.offset, args.pitch, args.target_height)
            if single:
                estimates.append(single)
            else:
                rejected += 1
            continue
        if states is not None:
            state = nearest_state(states, record.get('t', 0), args.tolerance)
            if state is None:
                unmatched += 1
                continue
        else:
            state = (record.get('t', 0), args.aircraft_lat, args.aircraft_lon,
                     args.agl, args.heading % 360, args.pitch)
        single = estimate(record, state, truth, args.target_height)
        if single:
            estimates.append(single)
        else:
            rejected += 1

    if not estimates:
        raise SystemExit(f'No records could be matched to an aircraft state '
                         f'({unmatched} outside the {args.tolerance} s tolerance). '
                         f'Check that the Pi clock and the flight log agree.')

    centred = [e for e in estimates if e['centred']]
    used = centred if (centred and not args.all_samples) else estimates
    note = ('centred samples only' if used is centred
            else 'ALL samples (none were centred)' if not centred
            else 'all samples (--all-samples)')

    yaw = summarise([e['yaw_est'] for e in used])
    pitch_down = summarise([e['pitch_down_est'] for e in used])
    headings = [e['heading_deg'] for e in used]
    pitches = [e['pitch_deg'] for e in used]
    ranges = [e['ground_range_m'] for e in used]
    heading_spread = max(headings)-min(headings) if len(headings) > 1 else 0.0

    print(f'\nSource: {args.source}')
    if truth:
        print(f'Truth point: {truth["lat"]:.7f}, {truth["lon"]:.7f}')
    print(f'Records: {len(records)} read, {len(estimates)} matched'
          + (f', {unmatched} unmatched' if unmatched else '')
          + (f', {rejected} rejected on geometry' if rejected else '')
          + f', {len(used)} used ({note})')
    print(f'Geometry: range {min(ranges):.1f}-{max(ranges):.1f} m, '
          f'depression {min(e["depression_deg"] for e in used):.1f}-'
          f'{max(e["depression_deg"] for e in used):.1f} deg'
          + ('' if tape else f', heading spread {heading_spread:.0f} deg'))

    print(f'\n  mount yaw          {yaw["mean"]:+8.2f} deg   '
          f'+/- {yaw["stdev"]:.2f}  (n={yaw["n"]}, '
          f'{yaw["min"]:+.2f} to {yaw["max"]:+.2f})')
    print(f'  mount pitch_down   {pitch_down["mean"]:8.2f} deg   '
          f'+/- {pitch_down["stdev"]:.2f}  (n={pitch_down["n"]}, '
          f'{pitch_down["min"]:.2f} to {pitch_down["max"]:.2f})')

    current = swarm.sensor(args.source)
    print(f'\n  currently in swarm.SENSORS: yaw {current["yaw"]:+.2f}, '
          f'pitch_down {current["pitch_down"]:.2f}')
    print(f'  change:                     yaw '
          f'{yaw["mean"]-current["yaw"]:+.2f}, pitch_down '
          f'{pitch_down["mean"]-current["pitch_down"]:+.2f}')

    ref = args.reference_range or statistics.fmean(ranges)
    print(f'\nWhat this is worth at {ref:.0f} m:')
    print(f'  correcting pitch_down moves the point '
          f'{abs(metres_at(pitch_down["mean"]-current["pitch_down"], ref)):7.1f} m')
    print(f'  correcting yaw moves the point        '
          f'{abs(metres_at(yaw["mean"]-current["yaw"], ref)):7.1f} m')
    print(f'  residual scatter leaves about         '
          f'{metres_at(max(yaw["stdev"], pitch_down["stdev"]), ref):7.1f} m')

    warnings = []
    if tape and not args.target_height:
        warnings.append('No --target-height given, so the detection box centre '
                        'is assumed to be on the ground. For a standing person '
                        'it is about half their height, and at these short '
                        'ranges that is the difference between a usable number '
                        'and a useless one. Measure it.')
    if tape:
        # A tape geometry is one fixed look angle by construction, so say what
        # that does and does not buy instead of warning about heading spread.
        wobble = abs(math.degrees(math.atan2(args.height+0.02, args.distance))
                     - math.degrees(math.atan2(args.height, args.distance)))
        warnings.append('Tape geometry: the nose alignment replaces the compass, '
                        'so this yaw is the mount alone - good. It is a single '
                        'look angle, so confirm pitch_down in flight before '
                        'trusting a long-range cue.')
        # Quote the cost at the range the operator actually cares about, not a
        # baked-in one: the Cruza's working range moved from 657 m to 309 m the
        # moment its real 25 deg mount was accounted for.
        quote_at = args.reference_range or 310.0
        warnings.append(f'Everything scales with the two tape numbers. At '
                        f'{args.height:.2f} m and {args.distance:.2f} m, 2 cm of '
                        f'height error moves pitch_down {wobble:.2f} deg, which '
                        f'is {metres_at(wobble, quote_at):.0f} m at '
                        f'{quote_at:.0f} m range.')
    elif heading_spread < 90 and len(used) > 1:
        warnings.append(f'Headings span only {heading_spread:.0f} deg, so the yaw '
                        'figure includes any compass bias. Observe the point from '
                        'headings 90 deg or more apart to separate them.')
    if len(set(round(p) for p in pitches)) < 2:
        warnings.append('Aircraft pitch barely varied, so pitch_down includes any '
                        'pitch estimation bias. Acceptable for level cruise.')
    if not centred:
        warnings.append(f'No sample had the target within {CENTRED_DEG:.0f} deg of '
                        'frame centre, so a field-of-view error is folded into '
                        'these angles. Re-fly with the target centred, or run the '
                        'fov mode first.')
    if max(yaw['stdev'], pitch_down['stdev']) > 1.0:
        warnings.append(f'Scatter is above 1 deg. Check the truth point, that the '
                        f'detector is locking the same object, and that the Pi '
                        f'clock is right.')
    if len(used) < 5:
        warnings.append(f'Only {len(used)} samples. Collect 20 or more.')
    for text in warnings:
        print(f'\n  ! {text}')

    block = dict(current, yaw=round(yaw['mean'], 2),
                 pitch_down=round(pitch_down['mean'], 2))
    print(f"\nPaste into swarm.SENSORS:\n    '{args.source}': "
          f"{{'hfov': {block['hfov']}, 'vfov': {block['vfov']}, "
          f"'yaw': {block['yaw']}, 'pitch_down': {block['pitch_down']}}},")
    print('Then re-run: python swarm/swarmtest.py bench --log <log>')

    if args.out:
        Path(args.out).write_text(json.dumps(
            {'source': args.source, 'truth': truth,
             'tape': ({'height_m': args.height, 'distance_m': args.distance,
                       'offset_m': args.offset} if tape else None),
             'generated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
             'records_read': len(records), 'matched': len(estimates),
             'used': len(used), 'selection': note,
             'yaw': yaw, 'pitch_down': pitch_down,
             'heading_spread_deg': heading_spread,
             'range_m': {'min': min(ranges), 'max': max(ranges)},
             'previous': current, 'suggested': block,
             'warnings': warnings, 'samples': used}, indent=2))
        print(f'Detail written to {args.out}')
    return 0


def tape_angles(model, height, distance, offset, pitch, target_height):
    """Where the marker truly sits off boresight, from the tape alone.

    The same geometry as tape_estimate, turned around: there the reported
    angles were evidence for an unknown mount, here the mount is known and the
    reported angles are what we are grading. Returns (az_true, el_true) in
    degrees off boresight, one fixed pair for a static setup.
    """
    if distance <= 0:
        raise SystemExit('--distance must be positive.')
    if height <= MIN_CAMERA_HEIGHT_M:
        raise SystemExit(f'--height must be more than {MIN_CAMERA_HEIGHT_M} m; '
                         f'below that the geometry is all noise.')
    effective = height-target_height
    if effective <= 0:
        raise SystemExit(f'--target-height {target_height} m is at or above the '
                         f'camera at {height} m, so there is no look-down angle.')
    ground_range = math.hypot(distance, offset)
    depression = math.degrees(math.atan2(effective, ground_range))
    if not swarm.MIN_DEPRESSION_DEG <= depression <= swarm.MAX_DEPRESSION_DEG:
        raise SystemExit(f'Depression {depression:.1f} deg is outside the usable '
                         f'band; move the marker.')
    return (wrap180(math.degrees(math.atan2(offset, distance))-model['yaw']),
            model['pitch_down']-pitch-depression)


def configured_fov(records, model):
    """The field of view the aircraft actually used to produce these angles.

    observe.py reports el_rel_deg = (0.5 - cy) * vfov_deg, so a field-of-view
    measurement is only ever a correction to the number the aircraft was
    configured with. Get that number wrong and the measurement is wrong by the
    same ratio, while looking perfectly plausible. Records carry it; SENSORS
    only claims it, so prefer the records and say so when they disagree.
    """
    seen = set()
    for record in records:
        pair = record.get('fov')
        if (isinstance(pair, (list, tuple)) and len(pair) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and v > 0 for v in pair)):
            seen.add((float(pair[0]), float(pair[1])))
    if not seen:
        return dict(model), (
            'These records do not say what field of view produced them, so the '
            'configured values below come from SENSORS. If the aircraft was set '
            'to anything else, the measurement is wrong by that ratio. Re-capture '
            'with a current observe.py to remove the guess.')
    if len(seen) > 1:
        raise SystemExit(
            'This capture mixes records taken with different fields of view ('
            + ', '.join(f'{h:g}x{v:g}' for h, v in sorted(seen))
            + '). Each needs measuring against its own, so split the file.')
    hfov, vfov = seen.pop()
    out = dict(model)
    out['hfov'], out['vfov'] = hfov, vfov
    note = None
    if abs(hfov-model['hfov']) > 0.05 or abs(vfov-model['vfov']) > 0.05:
        note = (f'Records were captured at {hfov:g} x {vfov:g} deg but SENSORS '
                f'says {model["hfov"]:g} x {model["vfov"]:g}. Measuring against '
                f'the records, which is what the aircraft used. Correct SENSORS '
                f'to match the aircraft.')
    return out, note


def fov(args):
    """Field of view from observations the mount angles cannot explain.

    Once yaw and pitch_down are known, a target away from the frame centre
    reports an angle that scales with the assumed field of view: if the real
    field of view is wider than configured, the reported angle is too small by
    the same ratio. So

        hfov_true = hfov_assumed * az_true / az_reported

    Samples near the centre carry no information and are skipped.

    Works from a flight (--log, or a static aircraft position) or from a TAPE
    geometry (--height/--distance/--offset), which is how anyone measures this
    before the airframe flies: over a five-metre baseline a tape is good to
    centimetres where a handheld GPS fix is good to metres.
    """
    records = load_records(args.records, args.cls, args.min_score)
    model = dict(swarm.sensor(args.source))
    if args.yaw is not None:
        model['yaw'] = args.yaw
    if args.pitch_down is not None:
        model['pitch_down'] = args.pitch_down
    model, fov_note = configured_fov(records, model)

    tape = args.height is not None or args.distance is not None
    truth, states, fixed = None, None, None
    if tape:
        if args.height is None or args.distance is None:
            raise SystemExit('Tape mode needs both --height and --distance.')
        fixed = tape_angles(model, args.height, args.distance, args.offset,
                            args.pitch, args.target_height)
    else:
        if args.lat is None or args.lon is None:
            raise SystemExit('Give a truth point (--lat/--lon) or a tape '
                             'geometry (--height/--distance).')
        truth = {'lat': args.lat, 'lon': args.lon}
        states = log_states(args.log, args.ground_alt) if args.log else None
        if states is None:
            # Without this a missing --heading reached `args.heading % 360`
            # and came back as a TypeError, which tells nobody anything.
            missing = [name for name, value in
                       (('--aircraft-lat', args.aircraft_lat),
                        ('--aircraft-lon', args.aircraft_lon),
                        ('--agl', args.agl), ('--heading', args.heading))
                       if value is None]
            if missing:
                raise SystemExit(
                    'Without --log the aircraft state has to be given in '
                    'full; missing ' + ', '.join(missing) + '. For a camera '
                    'on a ladder or a tripod use the tape geometry '
                    '(--height/--distance) instead.')

    h_ratios, v_ratios, skipped, matched = [], [], 0, 0
    for record in records:
        if tape:
            matched += 1
            az_true, el_true = fixed
            az_rep, el_rep = record['az_rel_deg'], record['el_rel_deg']
            if abs(az_rep) >= model['hfov']*EDGE_FRACTION/2 and abs(az_rep) > 1:
                h_ratios.append(az_true/az_rep)
            else:
                skipped += 1
            if abs(el_rep) >= model['vfov']*EDGE_FRACTION/2 and abs(el_rep) > 1:
                v_ratios.append(el_true/el_rep)
            continue
        if states is not None:
            state = nearest_state(states, record.get('t', 0), args.tolerance)
            if state is None:
                continue
        else:
            state = (record.get('t', 0), args.aircraft_lat, args.aircraft_lon,
                     args.agl, args.heading % 360, args.pitch)
        matched += 1
        _, lat, lon, agl, heading, pitch = state
        ground_range, bearing = swarm.distance_bearing(lat, lon, truth['lat'],
                                                       truth['lon'])
        if ground_range < 1.0 or agl <= MIN_CAMERA_HEIGHT_M:
            continue
        effective = agl-args.target_height
        if effective <= 0:
            continue
        depression = math.degrees(math.atan2(effective, ground_range))
        if not swarm.MIN_DEPRESSION_DEG <= depression <= swarm.MAX_DEPRESSION_DEG:
            continue
        az_true = wrap180(bearing-heading-model['yaw'])
        el_true = model['pitch_down']-pitch-depression
        az_rep, el_rep = record['az_rel_deg'], record['el_rel_deg']
        if abs(az_rep) >= model['hfov']*EDGE_FRACTION/2 and abs(az_rep) > 1:
            h_ratios.append(az_true/az_rep)
        else:
            skipped += 1
        if abs(el_rep) >= model['vfov']*EDGE_FRACTION/2 and abs(el_rep) > 1:
            v_ratios.append(el_true/el_rep)

    print(f'\nSource: {args.source}  (assuming yaw {model["yaw"]:+.2f}, '
          f'pitch_down {model["pitch_down"]:.2f})')
    if tape:
        print(f'Tape geometry: camera {args.height:.2f} m up, marker '
              f'{args.distance:.2f} m out, {args.offset:+.2f} m right, box '
              f'centre {args.target_height:.2f} m up '
              f'-> truly {fixed[0]:+.2f} az, {fixed[1]:+.2f} el off boresight')
    print(f'Records: {len(records)} read, {matched} matched to a usable geometry')
    if fov_note:
        print(f'\n  ! {fov_note}')
    if not h_ratios and not v_ratios:
        if not matched:
            raise SystemExit(
                'No record could be matched to a usable aircraft state. Check '
                'the time tolerance, and whether the log contains the launch '
                'point (see --ground-alt).')
        raise SystemExit(
            f'No sample was far enough off centre to measure a field of view '
            f'({skipped} too central). Put the target out towards the frame '
            f'edge: past {model["hfov"]*EDGE_FRACTION/2:.1f} deg horizontally '
            f'for hfov, {model["vfov"]*EDGE_FRACTION/2:.1f} deg vertically for '
            f'vfov. On a tape setup that is a sideways offset and a longer '
            f'distance; run `check` to find them before you build it.')
    for axis, ratios, key in (('hfov', h_ratios, 'hfov'), ('vfov', v_ratios, 'vfov')):
        if not ratios:
            print(f'  {axis}: no off-centre samples on this axis')
            continue
        s = summarise(ratios)
        print(f'  {axis}: configured {model[key]:.1f} deg -> measured '
              f'{model[key]*s["mean"]:.1f} deg  (scale {s["mean"]:.3f} '
              f'+/- {s["stdev"]:.3f}, n={s["n"]})')
        if abs(s['mean']-1) < 0.02:
            print(f'        within 2% of the configured value; leave it alone')
    print('\nRe-run the mount solve after changing a field of view: the two '
          'measurements are coupled.')
    return 0


def check(args):
    """What should the camera report for a setup you are about to build?

    Use this to lay out a ground calibration before anyone flies: pick a camera
    height and a marker distance, and this says where in the frame the marker
    will appear and whether it is in frame at all. A marker that lands near the
    frame centre is what you want for a mount measurement.
    """
    model = dict(swarm.sensor(args.source))
    if args.pitch_down is not None:
        model['pitch_down'] = args.pitch_down
    print(f'\n{args.source}: FOV {model["hfov"]:.0f} x {model["vfov"]:.0f} deg, '
          f'mount yaw {model["yaw"]:+.1f}, pitch_down {model["pitch_down"]:.1f}, '
          f'aircraft pitch {args.pitch:.1f}')
    working = args.height-args.target_height
    print(f'Camera {args.height:.2f} m above the ground'
          + (f', detection box centre {args.target_height:.2f} m up, so '
             f'{working:.2f} m of working height' if args.target_height else '')
          + '.')
    if not args.target_height:
        print('No --target-height given: assuming the detection sits on the '
              'ground. A standing person\'s box centre is about half their '
              'height, which at these ranges changes everything.')
    print()
    print(f'  {"distance":>9}  {"depression":>10}  {"el_rel":>8}  '
          f'{"frame y":>8}  in frame')
    for distance in args.distances:
        if distance <= 0 or working <= 0:
            continue
        depression = math.degrees(math.atan2(working, distance))
        el_rel = model['pitch_down']-args.pitch-depression
        frame_y = 0.5-el_rel/model['vfov']
        ok = abs(el_rel) <= model['vfov']/2
        flag = 'yes' if ok else 'NO - outside the frame'
        if ok and abs(el_rel) <= CENTRED_DEG:
            flag = 'yes, centred - use this one'
        print(f'  {distance:7.1f} m  {depression:9.1f}  {el_rel:+7.1f}  '
              f'{frame_y:7.2f}  {flag}')
    best = working/math.tan(math.radians(model['pitch_down']-args.pitch)) \
        if model['pitch_down'] > args.pitch and working > 0 else None
    if best:
        print(f'\nThe boresight meets the ground at {best:.1f} m. Put the marker '
              f'there for a centred mount measurement.')
        edge = model['pitch_down']-args.pitch-model['vfov']*EDGE_FRACTION/2
        if edge > 1:
            print(f'For a vertical field-of-view sample, move it out to about '
                  f'{working/math.tan(math.radians(edge)):.1f} m, which puts '
                  f'it {model["vfov"]*EDGE_FRACTION/2:.0f} deg off centre.')
    return 0


def capture(args):
    """Log every observer record, with a receive timestamp, to a file.

    Run on the aircraft's Pi alongside the detector. It binds the loopback port
    read-only and copies what it sees; it does not forward, answer or transmit
    anything. Safe to run while the dashboard's own tap is also reading, because
    this binds a *different* port - point the detector here, or run a second
    detector instance, rather than expecting to share one port. Two sockets on
    one UDP port steal packets from each other, they do not duplicate.
    """
    if not 15620 <= args.port <= 15629:
        raise SystemExit('--port must be an observer loopback port, 15620..15629')
    out = Path(args.out)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32768)
    sock.bind(('127.0.0.1', args.port))
    sock.settimeout(1)
    deadline = time.monotonic()+args.seconds
    kept = 0
    print(json.dumps({'event': 'capture_start', 'port': args.port,
                      'file': str(out), 'seconds': args.seconds}), flush=True)
    with out.open('a', encoding='utf-8') as handle:
        while time.monotonic() < deadline:
            try:
                packet = sock.recv(1024)
            except socket.timeout:
                continue
            if not 2 <= len(packet) <= 512:
                continue
            try:
                record = json.loads(packet)
            except ValueError:
                continue
            if not isinstance(record, dict) or 'az_rel_deg' not in record:
                continue
            record['received'] = round(time.time(), 3)
            handle.write(json.dumps(record, allow_nan=False)+'\n')
            handle.flush()
            kept += 1
            if kept % 10 == 0:
                print(json.dumps({'event': 'capture_progress', 'kept': kept}),
                      flush=True)
    print(json.dumps({'event': 'capture_done', 'kept': kept,
                      'file': str(out)}), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='mode', required=True)

    def add_geometry(p):
        p.add_argument('--records', required=True, help='capture file, JSON per line')
        p.add_argument('--lat', type=float, help='truth latitude')
        p.add_argument('--lon', type=float, help='truth longitude')
        p.add_argument('--log', help='flight log, for a moving aircraft')
        p.add_argument('--aircraft-lat', type=float, help='static aircraft latitude')
        p.add_argument('--aircraft-lon', type=float)
        p.add_argument('--agl', type=float, help='camera height above the ground')
        p.add_argument('--heading', type=float, help='true heading of the nose')
        p.add_argument('--pitch', type=float, default=0.0)
        p.add_argument('--cls', help='only use records of this class')
        p.add_argument('--min-score', type=float, default=0.0)
        p.add_argument('--tolerance', type=float, default=MATCH_TOLERANCE_S)
        p.add_argument('--target-height', type=float, default=0.0,
                       help='height of the DETECTION BOX CENTRE above the '
                            'ground - roughly half a standing person. Critical '
                            'for a ground calibration, negligible in flight')
        p.add_argument('--ground-alt', type=float,
                       help='launch-point altitude AMSL, when the log does not '
                            'contain the ground')

    s = sub.add_parser('solve', help='mount yaw and pitch_down from a known point')
    s.add_argument('--source', required=True, choices=sorted(swarm.SENSORS))
    add_geometry(s)
    s.add_argument('--height', type=float,
                   help='TAPE geometry: lens centre above the ground, metres')
    s.add_argument('--distance', type=float,
                   help='TAPE geometry: horizontal lens-to-marker along the nose')
    s.add_argument('--offset', type=float, default=0.0,
                   help='TAPE geometry: marker offset to the right, metres')
    s.add_argument('--all-samples', action='store_true',
                   help='use off-centre samples too (folds in FOV error)')
    s.add_argument('--reference-range', type=float,
                   help='range to quote the metres-per-degree impact at')
    s.add_argument('--out', help='write the detail as JSON here')
    s.set_defaults(func=solve)

    f = sub.add_parser('fov', help='field of view from off-centre observations')
    f.add_argument('--source', required=True, choices=sorted(swarm.SENSORS))
    add_geometry(f)
    f.add_argument('--yaw', type=float, help='known mount yaw, from solve')
    f.add_argument('--pitch-down', type=float, help='known mount pitch, from solve')
    f.add_argument('--height', type=float,
                   help='TAPE geometry: lens centre above the ground, metres')
    f.add_argument('--distance', type=float,
                   help='TAPE geometry: horizontal lens-to-marker along the nose')
    f.add_argument('--offset', type=float, default=0.0,
                   help='TAPE geometry: marker offset to the right, metres. '
                        'Needed for hfov; vfov comes from the distance')
    f.set_defaults(func=fov)

    c = sub.add_parser('check', help='plan a ground setup before building it')
    c.add_argument('--source', required=True, choices=sorted(swarm.SENSORS))
    c.add_argument('--height', type=float, required=True,
                   help='camera height above the ground, metres')
    c.add_argument('--pitch', type=float, default=0.0)
    c.add_argument('--pitch-down', type=float, help='override the configured mount')
    c.add_argument('--target-height', type=float, default=0.0,
                   help='height of the detection box centre above the ground')
    c.add_argument('--distances', type=float, nargs='+',
                   default=[3, 5, 7, 10, 15, 20, 30, 50],
                   help='marker distances to evaluate')
    c.set_defaults(func=check)

    p = sub.add_parser('capture', help='log observer records on an aircraft Pi')
    p.add_argument('--port', type=int, default=15620)
    p.add_argument('--out', required=True, help='append records here')
    p.add_argument('--seconds', type=float, default=300)
    p.set_defaults(func=capture)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
