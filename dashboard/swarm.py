"""Shared geolocated observation picture for the fleet. Contains no sender.

Turns each aircraft's advisory detections - angles off its own camera boresight -
into estimated points on the ground, then correlates points from different
aircraft into single areas of interest. The result is one picture an operator
reads, instead of three unrelated lists of angles.

This module is the authority for the geolocation maths. The browser panel keeps
its own copy for the Cruza-only view; test_swarm.py pins the two to the same
constants so they cannot drift apart silently.

Nothing here tasks, moves or transmits to an aircraft. A correlated track is a
stronger reason for a human to look somewhere, not a decision. Dispatch stays
where it already is: an operator confirms a cue, and the confirmed point lands in
the preview-only command panel. There is no MAVLink sender anywhere in this
system and this module does not add one.

Accuracy, honestly: a point is produced by assuming the camera's mounting angles
and field of view are as configured, that the aircraft's reported heading, pitch
and relative altitude are right, and that the ground under the target is as high
as the ground under the aircraft. Each of those is wrong by some amount. A
heading error moves the point sideways by roughly range x error-in-radians; a
depression error moves it along the bearing much faster at shallow angles. Treat
every point as a starting place to look, and re-pick it on the map.
"""
import math

# Per-aircraft camera model. Field of view must match the Pi observer config
# (observe.hfov_deg / observe.vfov_deg); the mount angles must be measured on
# the airframe. yaw 0 = camera along the nose, positive to the right.
# pitch_down = boresight tilted this far below level in level flight.
SENSORS = {
    'cruza':  {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0},
    'quadpi': {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 30.0},
    'rn03':   {'hfov': 90.0, 'vfov': 60.0, 'yaw': 0.0, 'pitch_down': 25.0},
}
DEFAULT_SENSOR = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}

MAX_RANGE_M = 1500      # never project an area of interest past this
DEFAULT_RANGE_M = 150   # used only when depression cannot give a range
MIN_AGL_M = 3           # below this the geometry is meaningless
MIN_DEPRESSION_DEG = 2  # shallower than this, range runs away
MAX_DEPRESSION_DEG = 85
FUSE_RADIUS_M = 120     # same class this close from two aircraft is one area
EARTH_R = 6371000.0


def _finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def project(lat, lon, bearing_deg, distance_m):
    """Point distance_m along a true bearing from lat/lon, on a sphere."""
    dr = distance_m/EARTH_R
    br, la, lo = math.radians(bearing_deg), math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la)*math.cos(dr)+math.cos(la)*math.sin(dr)*math.cos(br))
    lo2 = lo+math.atan2(math.sin(br)*math.sin(dr)*math.cos(la),
                        math.cos(dr)-math.sin(la)*math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2)+540) % 360-180


def distance_bearing(lat1, lon1, lat2, lon2):
    """Great-circle distance (m) and initial true bearing (deg), 1 -> 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2-p1, math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    distance = 2*EARTH_R*math.asin(min(1, math.sqrt(a)))
    y = math.sin(dlon)*math.cos(p2)
    x = math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dlon)
    return distance, (math.degrees(math.atan2(y, x))+360) % 360


def sensor(source):
    return SENSORS.get(source, DEFAULT_SENSOR)


def geolocate(obs, vehicle, model=None):
    """Estimate where one observation is, from the reporting aircraft's state.

    obs is an ObservationStore snapshot entry; vehicle is that aircraft's fleet
    snapshot. Returns bearing, lat/lon, slant range and whether the range had to
    be assumed. Any missing input yields None fields rather than a guess dressed
    up as a measurement.
    """
    model = model or sensor(obs.get('src'))
    out = {'bearing_deg': None, 'lat': None, 'lon': None,
           'range_m': None, 'estimated': True}
    if not isinstance(vehicle, dict) or not vehicle.get('online'):
        return out
    heading = vehicle.get('heading_deg')
    if not _finite(heading):
        return out
    out['bearing_deg'] = (heading+model['yaw']+obs['az_rel_deg']+360) % 360
    position = vehicle.get('position')
    if not isinstance(position, dict):
        return out
    lat, lon = position.get('latitude'), position.get('longitude')
    agl = position.get('altitude_relative_m')
    if not (_finite(lat) and _finite(lon)):
        return out
    pitch = vehicle.get('pitch_deg')
    pitch = pitch if _finite(pitch) else 0.0
    # Depression below the horizon of the ray through the detection box centre.
    depression = model['pitch_down']-pitch-obs['el_rel_deg']
    range_m = None
    if (_finite(agl) and agl > MIN_AGL_M
            and MIN_DEPRESSION_DEG < depression < MAX_DEPRESSION_DEG):
        range_m = min(MAX_RANGE_M, agl/math.tan(math.radians(depression)))
    out['range_m'] = range_m
    out['estimated'] = range_m is None
    use = DEFAULT_RANGE_M if range_m is None else range_m
    out['lat'], out['lon'] = project(lat, lon, out['bearing_deg'], use)
    return out


def cue(obs, vehicle, model=None):
    """One geolocated cue: the observation plus where it probably is."""
    geo = geolocate(obs, vehicle, model)
    return {'id': obs['id'], 'src': obs.get('src'), 'cls': obs['cls'],
            'score': obs['score'], 'count': obs.get('count', 1),
            'last_seen_age': obs.get('last_seen_age'),
            'az_rel_deg': obs['az_rel_deg'], 'el_rel_deg': obs['el_rel_deg'],
            **geo}


def cues(items, fleet):
    """Geolocate a whole store snapshot against the current fleet snapshot."""
    states = {v.get('name'): v for v in (fleet or []) if isinstance(v, dict)}
    return [cue(o, states.get(o.get('src'))) for o in (items or [])]


def fuse(cue_list, radius_m=FUSE_RADIUS_M):
    """Correlate located cues of the same class into shared areas of interest.

    Single-link clustering by ground distance, per class. Cues with no location
    cannot be correlated and each stay their own track, flagged unlocated: a cue
    without a position must still reach the operator, it just cannot be matched.

    sources is the point of the whole exercise. A track naming two aircraft is
    the same object seen from two angles - a far better reason to look than
    either report alone. span_m is how far apart those aircraft put it, which is
    the honest measure of how much to trust the point.
    """
    tracks = []
    by_class = {}
    for c in cue_list or []:
        if c.get('lat') is None:
            tracks.append(_track([c], located=False))
            continue
        by_class.setdefault(c['cls'], []).append(c)
    for group in by_class.values():
        clusters = []
        for c in sorted(group, key=lambda x: -x['score']):
            joined = None
            for cluster in clusters:
                if not cluster:
                    continue
                if any(distance_bearing(c['lat'], c['lon'], o['lat'], o['lon'])[0]
                       <= radius_m for o in cluster):
                    if joined is None:
                        joined = cluster
                        cluster.append(c)
                    else:
                        # c bridges two clusters: single-link merges them.
                        joined.extend(cluster)
                        cluster.clear()
            if joined is None:
                clusters.append([c])
        tracks.extend(_track(cluster) for cluster in clusters if cluster)
    # Cross-cued tracks first, then strongest; that is the operator's priority.
    tracks.sort(key=lambda t: (-len(t['sources']), -t['score']))
    return tracks


def _track(cluster, located=True):
    """Collapse one cluster of cues into a single area of interest."""
    sources = sorted({c['src'] for c in cluster if c.get('src')})
    best = max(cluster, key=lambda c: c['score'])
    track = {'id': '+'.join(sorted(c['id'] for c in cluster)),
             'cls': best['cls'], 'score': round(best['score'], 3),
             'sources': sources, 'cross_cued': len(sources) > 1,
             'reports': sum(c.get('count', 1) for c in cluster),
             'contributors': [{'src': c['src'], 'score': round(c['score'], 3),
                               'bearing_deg': None if c['bearing_deg'] is None
                               else round(c['bearing_deg'], 1),
                               'range_m': None if c['range_m'] is None
                               else round(c['range_m']),
                               'lat': c['lat'], 'lon': c['lon'],
                               'estimated': c['estimated']} for c in cluster],
             'located': located, 'lat': None, 'lon': None, 'span_m': None,
             'estimated': any(c['estimated'] for c in cluster)}
    freshest = min((c['last_seen_age'] for c in cluster
                    if _finite(c.get('last_seen_age'))), default=None)
    track['last_seen_age'] = freshest
    if not located:
        return track
    # Mean of the contributors' points. With two aircraft this halves the
    # sideways error from one bad heading; it does not fix a shared mount error.
    track['lat'] = round(sum(c['lat'] for c in cluster)/len(cluster), 7)
    track['lon'] = round(sum(c['lon'] for c in cluster)/len(cluster), 7)
    track['span_m'] = round(max(
        (distance_bearing(a['lat'], a['lon'], b['lat'], b['lon'])[0]
         for i, a in enumerate(cluster) for b in cluster[i+1:]), default=0.0), 1)
    return track


def picture(items, fleet, radius_m=FUSE_RADIUS_M):
    """The shared observation picture for /status: cues, tracks and a summary."""
    located = cues(items, fleet)
    tracks = fuse(located, radius_m)
    return {'cues': located, 'tracks': tracks,
            'sources': sorted({c['src'] for c in located if c.get('src')}),
            'cross_cued': sum(1 for t in tracks if t['cross_cued']),
            'fuse_radius_m': radius_m}
