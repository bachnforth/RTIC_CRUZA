"""Operator approval queue for handing an observer's cue to a live aircraft.

Every geolocated cue from the fleet's observers becomes a handover request
here: pending until the operator approves or denies it, or until it goes
stale. Nearby cues of the same class are merged into one request, so an
aircraft turning over a target (which changes the cue's azimuth bucket) does
not raise a new request each time. A decided request also absorbs later
sightings for a while, so a denied target is not offered again straight away.

Approval transmits nothing. It freezes the position that was approved and the
aircraft chosen to take it. If that aircraft has a live link, the browser
prefills its command workflow (fly to the point, loiter at it, or arm and fly
the mission already on the aircraft), where the command is still reviewed and
sent as usual. Otherwise the approval is *decision only*:
recorded and shown on the map for the safety pilot, with no command path at all. The
decision is the record: every one is appended to a JSON-lines log with the
image that was looked at.

State lives here, not in the browser, so every open page shows the same queue
and a reload loses nothing.
"""
import json
import threading
import time
from pathlib import Path

import swarm

PENDING_TTL_S = 180     # a pending request with no sighting this long expires
APPROVE_MAX_AGE_S = 60  # refuse to approve a position older than this
# swarm.picture() places every stored cue with the reporting aircraft's
# *current* heading and position, so a cue last seen several seconds ago is
# dragged across the map as the aircraft turns. Only a cue seen this recently
# is placed with telemetry from (nearly) the moment it was seen.
FRESH_CUE_S = 2.0
KEEP_DECIDED_S = 300    # decided requests absorb sightings, then drop off
MERGE_RADIUS_M = swarm.FUSE_RADIUS_M
MAX_REQUESTS = 40
HANDOVER_ACTIONS = ('goto', 'loiter', 'arm_mission')  # workflow commands an approval can prefill
# Commands that fly to the approved point. arm_mission launches the mission
# already on the aircraft, so the cue's position is not used and its age does
# not block the approval.
POINT_ACTIONS = ('goto', 'loiter')
HANDOVER_TARGETS = ('quadpi', 'rn03')   # aircraft a cue can be handed to
DENY_REASONS = ('False detection', 'Not a priority', 'Unsafe or airspace', 'Duplicate', '')


class HandoverQueue:
    def __init__(self, log_path, image_dir, clock=time.monotonic, wall=time.time):
        self.log_path = Path(log_path)
        self.image_dir = Path(image_dir)
        self.clock, self.wall = clock, wall
        self.lock = threading.Lock()
        self.requests = {}  # id -> request dict (image bytes kept in it)
        self.next_id = 1

    # -- incoming cues -----------------------------------------------------

    def sync(self, cues, image_for=None):
        """Fold the current geolocated cues into the queue.

        cues come from swarm.picture()['cues']; image_for(cue) returns that
        cue's image chip (JPEG bytes) if one has arrived, else None.
        """
        now = self.clock()
        with self.lock:
            for c in cues or []:
                if not (swarm._finite(c.get('lat')) and swarm._finite(c.get('lon'))):
                    continue  # nowhere to send anyone yet
                if (c.get('last_seen_age') or 0) > FRESH_CUE_S:
                    continue  # placed with later telemetry than it was seen with
                image = image_for(c) if image_for else None
                req = self._match(c)
                if req is None:
                    req = self._new(c, now)
                self._absorb(req, c, image, now)
            self._expire(now)

    def _match(self, c):
        best, best_d = None, None
        for r in self.requests.values():
            if r['cls'] != c['cls'] or r['status'] == 'expired':
                continue
            d, _ = swarm.distance_bearing(r['lat'], r['lon'], c['lat'], c['lon'])
            if d <= MERGE_RADIUS_M and (best_d is None or d < best_d):
                best, best_d = r, d
        return best

    def _new(self, c, now):
        if len(self.requests) >= MAX_REQUESTS:
            # Drop the oldest non-pending first; never silently lose a pending one
            # while a decided one could go instead.
            order = sorted(self.requests.values(),
                           key=lambda r: (r['status'] == 'pending', r['last_seen']))
            del self.requests[order[0]['id']]
        rid = f'H{self.next_id}'
        self.next_id += 1
        req = {'id': rid, 'cls': c['cls'], 'status': 'pending', 'sources': [],
               'cue_ids': {}, 'score': 0.0, 'sightings': 0,
               'first_seen': now, 'first_seen_wall': self.wall(),
               'image': None, 'image_rev': 0, 'image_score': -1.0,
               'lat': c['lat'], 'lon': c['lon'], 'decision': None}
        self.requests[rid] = req
        return req

    def _absorb(self, req, c, image, now):
        req['last_seen'] = now
        # Each merged cue carries its own running count of detections.
        req['cue_ids'][c['id']] = max(req['cue_ids'].get(c['id'], 0), c.get('count') or 1)
        req['sightings'] = sum(req['cue_ids'].values())
        if c['src'] not in req['sources']:
            req['sources'].append(c['src'])
        if req['status'] != 'pending':
            return  # an approved position is frozen; a denied one stays denied
        req['score'] = max(req['score'], c['score'])
        req.update(lat=c['lat'], lon=c['lon'], range_m=c.get('range_m'),
                   bearing_deg=c.get('bearing_deg'), estimated=c.get('estimated', True),
                   src=c['src'])
        # Keep the image from the strongest sighting that came with one.
        if image and (req['image'] is None or c['score'] >= req['image_score']):
            if image != req['image']:
                req['image_rev'] += 1
            req['image'], req['image_score'] = image, c['score']

    def _expire(self, now):
        for r in list(self.requests.values()):
            idle = now - r['last_seen']
            if r['status'] == 'pending' and idle > PENDING_TTL_S:
                r['status'] = 'expired'
                r['decided'] = now
                self._log(r, 'expired', None, '')
            elif r['status'] != 'pending' and idle > KEEP_DECIDED_S:
                del self.requests[r['id']]

    # -- operator decisions ------------------------------------------------

    def decide(self, rid, decision, target=None, reason='', live=(), action='goto'):
        """Approve or deny one pending request. Returns (ok, message, request).

        live names the aircraft whose control link accepts a point command;
        approving any other handover target is recorded as decision only.
        """
        now = self.clock()
        with self.lock:
            r = self.requests.get(rid)
            if r is None:
                return False, 'No such handover request (it may have expired).', None
            if r['status'] != 'pending':
                return False, f'Already {r["status"]}.', self._public(r, now)
            if decision == 'deny':
                if reason not in DENY_REASONS:
                    return False, 'Unknown reason.', self._public(r, now)
                r.update(status='denied', decided=now, decision={'reason': reason})
                self._log(r, 'denied', None, reason)
                return True, 'Denied.', self._public(r, now)
            if decision != 'approve':
                return False, 'Unknown decision.', self._public(r, now)
            if action not in HANDOVER_ACTIONS:
                return False, 'Unknown command.', self._public(r, now)
            if target not in HANDOVER_TARGETS:
                return False, 'That aircraft cannot take a handover.', self._public(r, now)
            mode = 'live' if target in live else 'decision-only'
            age = now - r['last_seen']
            if action in POINT_ACTIONS and age > APPROVE_MAX_AGE_S:
                return False, (f'Position is {age:.0f} s old; wait for a fresh sighting '
                               'or deny it.'), self._public(r, now)
            r.update(status='approved', decided=now,
                     decision={'target': target, 'action': action, 'mode': mode,
                               'lat': r['lat'], 'lon': r['lon'],
                               'position_age_s': round(age, 1)})
            self._log(r, 'approved', target, '', action, mode)
            return True, ('Approved.' if mode == 'live' else
                          'Approved (decision only): recorded, nothing sent.'), self._public(r, now)

    # -- views -------------------------------------------------------------

    def image(self, rid):
        with self.lock:
            r = self.requests.get(rid)
            return r['image'] if r else None

    def snapshot(self):
        now = self.clock()
        with self.lock:
            self._expire(now)
            out = [self._public(r, now) for r in self.requests.values()]
        # Pending first (newest first), then the recently decided.
        out.sort(key=lambda r: (r['status'] != 'pending', r['age_s']))
        return out

    def _public(self, r, now):
        return {'id': r['id'], 'status': r['status'], 'cls': r['cls'],
                'src': r.get('src'), 'sources': list(r['sources']),
                'score': round(r['score'], 3), 'sightings': r['sightings'],
                'lat': r['lat'], 'lon': r['lon'],
                'range_m': None if r.get('range_m') is None else round(r['range_m']),
                'bearing_deg': None if r.get('bearing_deg') is None else round(r['bearing_deg']),
                'estimated': r.get('estimated', True),
                'age_s': round(now - r['last_seen'], 1),
                'open_s': round(now - r['first_seen'], 1),
                'image_rev': r['image_rev'] if r['image'] else 0,
                'decision': r['decision'],
                'decided_s': None if 'decided' not in r else round(now - r['decided'], 1)}

    def _log(self, r, outcome, target, reason, action=None, mode=None):
        stamp = time.strftime('%Y%m%dT%H%M%S', time.localtime(self.wall()))
        image_file = None
        if r['image']:
            try:
                self.image_dir.mkdir(parents=True, exist_ok=True)
                image_file = self.image_dir/f'{stamp}-{r["id"]}.jpg'
                image_file.write_bytes(r['image'])
            except OSError:
                image_file = None
        entry = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(self.wall())),
                 'id': r['id'], 'outcome': outcome, 'cls': r['cls'], 'src': r.get('src'),
                 'sources': r['sources'], 'score': round(r['score'], 3),
                 'lat': round(r['lat'], 7), 'lon': round(r['lon'], 7),
                 'range_m': r.get('range_m'), 'estimated': r.get('estimated', True),
                 'sightings': r['sightings'], 'target': target, 'action': action, 'mode': mode, 'reason': reason,
                 'image': image_file.name if image_file else None}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(entry, allow_nan=False)+'\n')
        except (OSError, ValueError):
            pass
