#!/usr/bin/env python3
"""Swarm observation test: can three aircraft share geolocated detections?

Answers one question with numbers: if the Cruza, the TFW drone and the quad each
report what their camera sees, does the architecture turn that into one shared
picture with usable positions, and does it recognise when two of them are
looking at the same thing?

The method is a round trip against known truth. A target is placed at a known
lat/lon. For each aircraft, given its real position and attitude, the harness
computes the angles off its camera boresight that the aircraft *would* report,
and emits exactly the record companion/observe.py publishes. Those records go
through the real dashboard code - observations.ObservationStore.validate, then
swarm.geolocate and swarm.fuse - and the resulting point is compared back to the
truth it came from. Error in metres is the answer.

Because the round trip is exact when every input is exact, the useful part is
the sensitivity sweep: the harness repeats the measurement with the heading,
mount pitch and altitude wrong by realistic amounts, and reports how far the
point moves. That tells you what calibration is worth before a flight.

Modes:
  bench      offline, no aircraft, no network. Replays a real flight log for the
             Cruza's track and scores accuracy, cross-cueing and store latency.
  inject     publish records to an observer loopback port, as observe.py does.
             Run on an aircraft's Pi to exercise the real tap -> SSH -> dashboard
             path with positions you control. Needs --lat/--lon truth and the
             aircraft's own state.
  track      summarise a flight log's position/attitude, to pick a bench window.

Nothing in this file opens a serial port, speaks MAVLink, writes to an aircraft
or changes a route, service or parameter. inject writes JSON to one loopback UDP
port and nothing else. The records are advisory cues for a human to look at, and
the dashboard's dispatch stays operator-gated and preview-only.
"""
import argparse
import json
import math
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'dashboard'))
import swarm                                        # noqa: E402
from observations import ObservationStore, validate  # noqa: E402

MAX_RECORD_BYTES = 512   # observe.py's own cap; observe-tap.py drops anything over
FUSE_TOLERANCE_M = 400   # how far apart two aircraft may put a target and still fuse


# --------------------------------------------------------------------------
# Truth -> what an aircraft's camera would report (the inverse of geolocate)
# --------------------------------------------------------------------------

def wrap180(deg):
    return (deg+180) % 360-180


def observation_of(target, vehicle, model, score=0.8, cls='person'):
    """The record this aircraft's observer would publish for this target.

    Returns None when the target is outside the camera's field of view - which
    is itself a result worth having, because it says this aircraft cannot see
    the thing the other one is reporting.
    """
    pos = vehicle['position']
    ground_range, bearing = swarm.distance_bearing(
        pos['latitude'], pos['longitude'], target['lat'], target['lon'])
    agl = pos['altitude_relative_m']
    az_rel = wrap180(bearing-vehicle['heading_deg']-model['yaw'])
    if ground_range <= 0:
        return None
    depression = math.degrees(math.atan2(agl, ground_range))
    el_rel = model['pitch_down']-(vehicle.get('pitch_deg') or 0.0)-depression
    if abs(az_rel) > model['hfov']/2 or abs(el_rel) > model['vfov']/2:
        return None
    # observe.py maps the box centre to angles linearly across the field of
    # view, so invert that exactly: a detection centred here produces these
    # angles, and the record carries the same rounding the aircraft applies.
    cx = az_rel/model['hfov']+0.5
    cy = 0.5-el_rel/model['vfov']
    bbox = [max(0.0, min(1.0, cx-0.06)), max(0.0, min(1.0, cy-0.08)), 0.12, 0.16]
    return {'t': round(time.time(), 2), 'seq': 1, 'cls': cls,
            'score': round(score, 3), 'az_rel_deg': round(az_rel, 2),
            'el_rel_deg': round(el_rel, 2),
            'bbox': [round(v, 4) for v in bbox]}


def vehicle_state(name, lat, lon, agl, heading, pitch=0.0, online=True):
    """A fleet snapshot shaped exactly like fleet.VehicleState.snapshot()."""
    return {'name': name, 'online': online, 'heading_deg': heading,
            'pitch_deg': pitch,
            'position': {'latitude': lat, 'longitude': lon,
                         'altitude_relative_m': agl, 'heading_deg': heading}}


# --------------------------------------------------------------------------
# Flight log -> a real track to fly the test against
# --------------------------------------------------------------------------

def load_track(path, limit=400):
    """Read GPS and ATT records from a .records.json flight log.

    Returns samples of (lat, lon, alt_amsl, course, pitch). Altitude above the
    launch point is derived by the caller, because the log's GPS altitude is
    above sea level and the dashboard works in relative altitude.
    """
    data = json.loads(Path(path).read_text())
    gps = [g for g in data.get('GPS', [])
           if g.get('Status', 0) >= 3 and g.get('Lat') and g.get('Lng')]
    att = sorted(((a.get('TimeUS', 0), a.get('Pitch', 0.0), a.get('Yaw'))
                  for a in data.get('ATT', [])), key=lambda r: r[0])
    if not gps:
        raise SystemExit(f'No 3D-fix GPS records in {path}')
    step = max(1, len(gps)//limit)
    samples = []
    for g in gps[::step]:
        pitch, yaw = 0.0, g.get('GCrs', 0.0)
        if att:
            # Nearest attitude record by log time; the two streams are logged
            # independently, so do not assume they line up index for index.
            i = min(range(len(att)), key=lambda k: abs(att[k][0]-g.get('TimeUS', 0)))
            pitch = att[i][1] or 0.0
            if att[i][2] is not None:
                yaw = att[i][2]
        samples.append((g['Lat'], g['Lng'], g.get('Alt', 0.0), yaw, pitch))
    return samples


def moving_window(samples, min_agl=30):
    """The part of the track that is actually flying, in relative altitude."""
    ground = min(s[2] for s in samples)
    flying = [(lat, lon, alt-ground, crs, pitch)
              for lat, lon, alt, crs, pitch in samples if alt-ground >= min_agl]
    return flying


# --------------------------------------------------------------------------
# bench: the offline end-to-end measurement
# --------------------------------------------------------------------------

def run_chain(records, fleet, now=1000.0):
    """Push records through the real store, then geolocate and fuse.

    records is a list of (source, record). Returns the picture plus how long the
    store took, so a slow validate shows up as a number rather than a feeling.
    """
    store = ObservationStore()
    kept = 0
    start = time.perf_counter()
    for source, record in records:
        kept += bool(store.add(record, now=now, source=source))
    add_ms = (time.perf_counter()-start)*1000
    start = time.perf_counter()
    picture = swarm.picture(store.snapshot(now=now), fleet)
    picture_ms = (time.perf_counter()-start)*1000
    picture['_kept'] = kept
    picture['_offered'] = len(records)
    picture['_add_ms'] = add_ms
    picture['_picture_ms'] = picture_ms
    return picture


def wire_check(record):
    """Would this record survive the real wire: observe.py's cap, the tap's
    framing bounds and the server's validate()?"""
    raw = json.dumps(record, allow_nan=False).encode()
    return {'bytes': len(raw), 'under_cap': len(raw) <= MAX_RECORD_BYTES,
            'tap_framing': 2 <= len(raw) <= 512,
            'validates': validate(json.loads(raw)) is not None}


def accuracy_case(target, vehicles, bias=None):
    """Geolocation error per aircraft for one target, with optional bias.

    bias perturbs only what the *dashboard* believes - heading, mount pitch,
    altitude - while the record is generated from the truth. That is exactly the
    real failure: the aircraft reports an honest angle and we resolve it with a
    wrong model.
    """
    bias = bias or {}
    results = []
    for name, truth_state in vehicles.items():
        model = swarm.sensor(name)
        record = observation_of(target, truth_state, model, cls=target['cls'])
        if record is None:
            results.append({'src': name, 'visible': False})
            continue
        believed = json.loads(json.dumps(truth_state))
        believed['heading_deg'] += bias.get('heading_deg', 0.0)
        believed['position']['heading_deg'] = believed['heading_deg']
        believed['position']['altitude_relative_m'] *= 1+bias.get('alt_pct', 0.0)/100
        believed_model = dict(model)
        believed_model['pitch_down'] += bias.get('pitch_down_deg', 0.0)
        store = ObservationStore()
        store.add(record, now=1000.0, source=name)
        snap = store.snapshot(now=1000.0)
        if not snap:
            results.append({'src': name, 'visible': True, 'kept': False})
            continue
        geo = swarm.geolocate(snap[0], believed, believed_model)
        if geo['lat'] is None:
            results.append({'src': name, 'visible': True, 'kept': True,
                            'located': False})
            continue
        error, _ = swarm.distance_bearing(geo['lat'], geo['lon'],
                                          target['lat'], target['lon'])
        results.append({'src': name, 'visible': True, 'kept': True,
                        'located': True, 'error_m': error,
                        'range_m': geo['range_m'], 'bearing_deg': geo['bearing_deg'],
                        'estimated': geo['estimated'],
                        'wire': wire_check(record)})
    return results


def bench(args):
    log = args.log and Path(args.log)
    report = {'generated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'log': str(log) if log else None, 'checks': [], 'verdict': 'PASS'}

    def check(name, ok, detail):
        report['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        if not ok:
            report['verdict'] = 'FAIL'
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    # --- the scenario ------------------------------------------------------
    if log:
        samples = moving_window(load_track(log))
        if len(samples) < 20:
            raise SystemExit(f'{log}: not enough airborne samples to fly the test')
        mid = samples[len(samples)//2]
        cruza = vehicle_state('cruza', mid[0], mid[1], mid[2], mid[3] % 360, mid[4])
        print(f'Cruza state from {log.name}: '
              f'{mid[0]:.6f},{mid[1]:.6f} {mid[2]:.0f} m AGL '
              f'hdg {mid[3] % 360:.0f} pitch {mid[4]:.1f} '
              f'({len(samples)} airborne samples)')
    else:
        cruza = vehicle_state('cruza', 33.7235577, -85.9070862, 100.0, 90.0, -2.0)
        print('Cruza state: synthetic (no --log given)')

    # Place the truth target where the Cruza is actually looking, then put the
    # other two aircraft where they can see the same ground from other angles.
    model = swarm.sensor('cruza')
    look = (cruza['heading_deg']+model['yaw']) % 360
    depression = model['pitch_down']-cruza['pitch_deg']
    ground_range = cruza['position']['altitude_relative_m']/math.tan(math.radians(depression))
    t_lat, t_lon = swarm.project(cruza['position']['latitude'],
                                 cruza['position']['longitude'], look, ground_range)
    target = {'lat': t_lat, 'lon': t_lon, 'cls': 'person'}
    print(f'Truth target: {t_lat:.6f},{t_lon:.6f} '
          f'({ground_range:.0f} m along {look:.0f} deg from the Cruza)')

    # quadpi orbits the target from the south-west at 60 m; rn03 from the
    # north-east at 45 m. Each is positioned and pointed so the target is in
    # frame - which is the whole premise of a cross-cue.
    vehicles = {'cruza': cruza}
    for name, offset_bearing, offset_m, agl in (('quadpi', 225.0, 90.0, 60.0),
                                                ('rn03', 45.0, 70.0, 45.0)):
        m = swarm.sensor(name)
        lat, lon = swarm.project(t_lat, t_lon, offset_bearing, offset_m)
        _, to_target = swarm.distance_bearing(lat, lon, t_lat, t_lon)
        vehicles[name] = vehicle_state(name, lat, lon, agl, to_target, 0.0)
        print(f'{name} state: {lat:.6f},{lon:.6f} {agl:.0f} m AGL '
              f'hdg {to_target:.0f} (FOV {m["hfov"]:.0f}x{m["vfov"]:.0f}, '
              f'mount {m["pitch_down"]:.0f} deg down)')

    # --- 1. every aircraft can see it and report a legal record ------------
    print('\n1. Each aircraft generates a wire-legal observation')
    perfect = accuracy_case(target, vehicles)
    seen = [r for r in perfect if r.get('visible')]
    check('all three aircraft have the target in frame',
          len(seen) == 3, f'{len(seen)}/3 in field of view')
    bad_wire = [r['src'] for r in seen
                if not all(r.get('wire', {}).get(k) for k in
                           ('under_cap', 'tap_framing', 'validates'))]
    sizes = [r['wire']['bytes'] for r in seen if 'wire' in r]
    check('records pass the 512-byte cap, tap framing and server validate',
          not bad_wire, f'max {max(sizes, default=0)} B, '
                        f'{len(sizes)} records, rejects: {bad_wire or "none"}')

    # --- 2. the maths round-trips -----------------------------------------
    print('\n2. Geolocation round-trips against truth (perfect telemetry)')
    located = [r for r in seen if r.get('located')]
    check('every visible observation resolves to a point',
          len(located) == len(seen), f'{len(located)}/{len(seen)} located')
    worst = max((r['error_m'] for r in located), default=float('inf'))
    for r in sorted(located, key=lambda x: x['src']):
        print(f'     {r["src"]:7s} error {r["error_m"]:7.2f} m  '
              f'range {r["range_m"]:6.1f} m  bearing {r["bearing_deg"]:5.1f} deg')
    check('round-trip error under 1 m with exact inputs',
          worst < 1.0, f'worst {worst:.2f} m')

    # --- 3. cross-cueing: do two aircraft fuse into one area? -------------
    print('\n3. Cross-cueing: the same object seen by three aircraft')
    records = []
    for name, state in vehicles.items():
        rec = observation_of(target, state, swarm.sensor(name), cls=target['cls'])
        if rec:
            records.append((name, rec))
    fleet = list(vehicles.values())
    picture = run_chain(records, fleet)
    check('every record is kept by the store',
          picture['_kept'] == picture['_offered'],
          f'{picture["_kept"]}/{picture["_offered"]} kept')
    cross = [t for t in picture['tracks'] if t['cross_cued']]
    check('the three reports correlate into one cross-cued area',
          len(picture['tracks']) == 1 and len(cross) == 1
          and len(cross[0]['sources']) == 3,
          f'{len(picture["tracks"])} track(s), '
          f'sources {cross[0]["sources"] if cross else []}, '
          f'span {cross[0]["span_m"] if cross else "n/a"} m')
    if cross:
        err, _ = swarm.distance_bearing(cross[0]['lat'], cross[0]['lon'],
                                        target['lat'], target['lon'])
        check('the fused point lands on the truth',
              err < 1.0, f'{err:.2f} m from truth')

    # --- 4. distinct objects must NOT be merged ---------------------------
    print('\n4. A second, separate object stays a separate area')
    far_lat, far_lon = swarm.project(t_lat, t_lon, 90.0, 500.0)
    second = {'lat': far_lat, 'lon': far_lon, 'cls': 'person'}
    far_records = list(records)
    for name, state in vehicles.items():
        rec = observation_of(second, state, swarm.sensor(name), cls='person')
        if rec:
            far_records.append((name, rec))
    far_picture = run_chain(far_records, fleet)
    check('a target 500 m away is a second track, not merged into the first',
          len(far_picture['tracks']) == 2,
          f'{len(far_picture["tracks"])} tracks from '
          f'{len(far_records)} reports of 2 objects')

    # --- 5. sensitivity: what calibration actually buys -------------------
    print('\n5. Sensitivity to the errors we really have')
    rows = []
    for label, bias in (('heading off by 1 deg', {'heading_deg': 1.0}),
                        ('heading off by 5 deg', {'heading_deg': 5.0}),
                        ('mount pitch off by 1 deg', {'pitch_down_deg': 1.0}),
                        ('mount pitch off by 5 deg', {'pitch_down_deg': 5.0}),
                        ('relative altitude off by 10%', {'alt_pct': 10.0})):
        case = [r for r in accuracy_case(target, vehicles, bias) if r.get('located')]
        by_src = {r['src']: r['error_m'] for r in case}
        rows.append({'bias': label, 'errors_m': {k: round(v, 1)
                                                 for k, v in by_src.items()}})
        worst_src = max(by_src, key=by_src.get) if by_src else None
        print(f'     {label:28s} worst {by_src.get(worst_src, 0):7.1f} m '
              f'({worst_src})  ' +
              '  '.join(f'{k} {v:.0f} m' for k, v in sorted(by_src.items())))
        # Does the fleet still agree it is one object once biased?
        biased = []
        for name, state in vehicles.items():
            rec = observation_of(target, state, swarm.sensor(name), cls='person')
            if rec:
                biased.append((name, rec))
        believed_fleet = json.loads(json.dumps(fleet))
        for v in believed_fleet:
            v['heading_deg'] += bias.get('heading_deg', 0.0)
            v['position']['heading_deg'] = v['heading_deg']
            v['position']['altitude_relative_m'] *= 1+bias.get('alt_pct', 0.0)/100
        saved = {k: dict(v) for k, v in swarm.SENSORS.items()}
        try:
            for k in swarm.SENSORS:
                swarm.SENSORS[k]['pitch_down'] += bias.get('pitch_down_deg', 0.0)
            biased_picture = run_chain(biased, believed_fleet)
        finally:
            swarm.SENSORS.update(saved)
        rows[-1]['tracks'] = len(biased_picture['tracks'])
        rows[-1]['cross_cued'] = biased_picture['cross_cued']
    report['sensitivity'] = rows
    tolerable = [r for r in rows if r['errors_m']
                 and max(r['errors_m'].values()) <= FUSE_TOLERANCE_M]
    check('a 1-degree heading error stays inside the fusion tolerance',
          any(r['bias'].endswith('1 deg') and r['cross_cued'] >= 1 for r in rows),
          f'{len(tolerable)}/{len(rows)} bias cases stay under '
          f'{FUSE_TOLERANCE_M} m worst-case')

    # --- 6. a cue with no telemetry must still reach the operator ---------
    print('\n6. Degraded cases')
    offline = {'cruza': cruza, 'quadpi': vehicles['quadpi']}
    dark_fleet = [cruza, dict(vehicles['quadpi'], online=False)]
    dark_records = [(n, observation_of(target, s, swarm.sensor(n), cls='person'))
                    for n, s in offline.items()]
    dark_records = [(n, r) for n, r in dark_records if r]
    dark = run_chain(dark_records, dark_fleet)
    unlocated = [t for t in dark['tracks'] if not t['located']]
    check('an aircraft with no telemetry still raises an unlocated cue',
          len(unlocated) == 1 and len(dark['tracks']) == 2,
          f'{len(dark["tracks"])} tracks, {len(unlocated)} unlocated')
    junk = [('cruza', {'cls': '../etc/passwd', 'score': 0.9, 'az_rel_deg': 0,
                       'el_rel_deg': 0, 'bbox': [0, 0, 1, 1]}),
            ('cruza', {'cls': 'person', 'score': float('inf'), 'az_rel_deg': 0,
                       'el_rel_deg': 0, 'bbox': [0, 0, 1, 1]}),
            ('not a plane!', records[0][1] if records else None)]
    junk = [(s, r) for s, r in junk if r is not None]
    junk_picture = run_chain(junk, fleet)
    check('malformed records and unknown sources are dropped',
          junk_picture['_kept'] == 0, f'{junk_picture["_kept"]}/{len(junk)} kept')

    # --- 7. throughput ----------------------------------------------------
    print('\n7. Store and picture cost at a realistic fleet rate')
    load = []
    for i in range(150):
        name = ('cruza', 'quadpi', 'rn03')[i % 3]
        rec = observation_of(target, vehicles[name], swarm.sensor(name),
                             cls=('person', 'car', 'truck')[i % 3])
        if rec:
            rec['az_rel_deg'] = round(rec['az_rel_deg']+(i % 7)-3, 2)
            load.append((name, rec))
    loaded = run_chain(load, fleet)
    check('150 reports resolve in well under a status poll',
          loaded['_add_ms']+loaded['_picture_ms'] < 250,
          f'store {loaded["_add_ms"]:.1f} ms + picture '
          f'{loaded["_picture_ms"]:.1f} ms for {len(load)} reports '
          f'-> {len(loaded["tracks"])} tracks')

    report['picture'] = {'tracks': picture['tracks'],
                         'sources': picture['sources'],
                         'cross_cued': picture['cross_cued']}
    passed = sum(1 for c in report['checks'] if c['ok'])
    print(f'\n{report["verdict"]}: {passed}/{len(report["checks"])} checks passed')
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, default=str))
        print(f'Report written to {args.out}')
    return 0 if report['verdict'] == 'PASS' else 1


# --------------------------------------------------------------------------
# inject: drive the real wire on an aircraft
# --------------------------------------------------------------------------

def inject(args):
    """Publish records for a known target to an observer loopback port.

    Run this on an aircraft's Pi in place of the camera detector. The record is
    byte-for-byte what observe.py emits, so observe-tap.py, the SSH framing, the
    server's validate() and the dashboard's geolocation are all exercised for
    real. It is clearly a test source: the class name is yours to set and the
    positions are the ones you pass in.
    """
    if not 15620 <= args.port <= 15629:
        raise SystemExit('--port must be an observer loopback port, 15620..15629')
    model = dict(swarm.sensor(args.source))
    for key, value in (('hfov', args.hfov), ('vfov', args.vfov),
                       ('yaw', args.mount_yaw), ('pitch_down', args.mount_pitch_down)):
        if value is not None:
            model[key] = value
    state = vehicle_state(args.source, args.aircraft_lat, args.aircraft_lon,
                          args.agl, args.heading, args.pitch)
    record = observation_of({'lat': args.lat, 'lon': args.lon, 'cls': args.cls},
                            state, model, score=args.score, cls=args.cls)
    if record is None:
        raise SystemExit('Target is outside the camera field of view from that '
                         'aircraft state - nothing to inject. Check --heading, '
                         '--agl and the mount angles.')
    wire = wire_check(record)
    if not all(wire[k] for k in ('under_cap', 'tap_framing', 'validates')):
        raise SystemExit(f'Generated record would not survive the wire: {wire}')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(json.dumps({'event': 'inject_start', 'source': args.source,
                      'port': args.port, 'count': args.count,
                      'record_bytes': wire['bytes'], 'record': record}))
    for i in range(args.count):
        record['t'] = round(time.time(), 2)
        record['seq'] = i+1
        sock.sendto(json.dumps(record, allow_nan=False).encode(),
                    ('127.0.0.1', args.port))
        time.sleep(max(0.05, 1.0/args.rate))
    print(json.dumps({'event': 'inject_done', 'sent': args.count}))
    return 0


def track(args):
    samples = load_track(args.log)
    flying = moving_window(samples)
    ground = min(s[2] for s in samples)
    print(f'{args.log}: {len(samples)} sampled GPS fixes, '
          f'{len(flying)} at or above 30 m AGL (ground {ground:.1f} m AMSL)')
    for label, s in (('first airborne', flying[0] if flying else None),
                     ('mid airborne', flying[len(flying)//2] if flying else None),
                     ('last airborne', flying[-1] if flying else None)):
        if s:
            print(f'  {label:15s} {s[0]:.6f},{s[1]:.6f}  {s[2]:6.1f} m AGL  '
                  f'hdg {s[3] % 360:5.1f}  pitch {s[4]:5.1f}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='mode', required=True)

    b = sub.add_parser('bench', help='offline end-to-end measurement')
    b.add_argument('--log', help='.records.json flight log for the Cruza track')
    b.add_argument('--out', help='write the JSON report here')
    b.set_defaults(func=bench)

    t = sub.add_parser('track', help='summarise a flight log')
    t.add_argument('log')
    t.set_defaults(func=track)

    i = sub.add_parser('inject', help='publish test records on an aircraft')
    i.add_argument('--source', required=True, choices=sorted(swarm.SENSORS))
    i.add_argument('--port', type=int, default=15620)
    i.add_argument('--lat', type=float, required=True, help='target truth latitude')
    i.add_argument('--lon', type=float, required=True, help='target truth longitude')
    i.add_argument('--aircraft-lat', type=float, required=True)
    i.add_argument('--aircraft-lon', type=float, required=True)
    i.add_argument('--agl', type=float, required=True, help='metres above launch')
    i.add_argument('--heading', type=float, required=True, help='true heading deg')
    i.add_argument('--pitch', type=float, default=0.0)
    i.add_argument('--cls', default='person')
    i.add_argument('--score', type=float, default=0.8)
    i.add_argument('--count', type=int, default=20)
    i.add_argument('--rate', type=float, default=2.0)
    i.add_argument('--hfov', type=float)
    i.add_argument('--vfov', type=float)
    i.add_argument('--mount-yaw', type=float)
    i.add_argument('--mount-pitch-down', type=float)
    i.set_defaults(func=inject)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
