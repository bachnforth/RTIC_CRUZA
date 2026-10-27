"""Tests for the shared observation picture and the swarm test harness.

Run: python swarm/test_swarm.py
"""
import json
import math
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'dashboard'))
import swarm
import swarmtest
from observations import ObservationStore

FIELD = (33.7235577, -85.9070862)


def state(name, lat=FIELD[0], lon=FIELD[1], agl=100.0, heading=0.0, pitch=0.0,
          online=True):
    return swarmtest.vehicle_state(name, lat, lon, agl, heading, pitch, online)


def obs(src='cruza', cls='person', az=0.0, el=0.0, score=0.8, oid=None):
    return {'id': oid or f'{src}/{cls}@0', 'src': src, 'cls': cls, 'score': score,
            'az_rel_deg': az, 'el_rel_deg': el, 'bbox': [0.4, 0.4, 0.1, 0.1],
            'count': 1, 'last_seen_age': 1.0}


class GeolocateTests(unittest.TestCase):
    def test_bearing_is_heading_plus_mount_plus_offset(self):
        g = swarm.geolocate(obs(az=20.0), state('cruza', heading=100.0))
        self.assertAlmostEqual(g['bearing_deg'], 120.0, places=6)

    def test_bearing_wraps_through_north(self):
        g = swarm.geolocate(obs(az=-30.0), state('cruza', heading=10.0))
        self.assertAlmostEqual(g['bearing_deg'], 340.0, places=6)

    def test_range_comes_from_depression_and_height(self):
        # 100 m up, boresight 15 deg down, level flight, detection centred.
        g = swarm.geolocate(obs(), state('cruza', agl=100.0))
        self.assertAlmostEqual(g['range_m'], 100/math.tan(math.radians(15)), places=3)
        self.assertFalse(g['estimated'])

    def test_aircraft_pitch_changes_the_depression(self):
        nose_up = swarm.geolocate(obs(), state('cruza', agl=100.0, pitch=5.0))
        level = swarm.geolocate(obs(), state('cruza', agl=100.0, pitch=0.0))
        self.assertGreater(nose_up['range_m'], level['range_m'])

    def test_range_is_capped_not_runaway(self):
        g = swarm.geolocate(obs(el=12.9), state('cruza', agl=100.0))
        self.assertLessEqual(g['range_m'], swarm.MAX_RANGE_M)

    def test_shallow_or_upward_look_gives_no_range(self):
        g = swarm.geolocate(obs(el=20.0), state('cruza', agl=100.0))
        self.assertIsNone(g['range_m'])
        self.assertTrue(g['estimated'])
        self.assertIsNotNone(g['lat'])  # still placed, at the default range

    def test_low_altitude_gives_no_range(self):
        g = swarm.geolocate(obs(), state('cruza', agl=1.0))
        self.assertIsNone(g['range_m'])

    def test_offline_or_headingless_aircraft_yields_nothing(self):
        self.assertIsNone(swarm.geolocate(obs(), state('cruza', online=False))['lat'])
        no_heading = state('cruza')
        no_heading['heading_deg'] = None
        self.assertIsNone(swarm.geolocate(obs(), no_heading)['bearing_deg'])

    def test_each_source_uses_its_own_mount_angles(self):
        # Same angles from the same place must not land in the same spot when
        # the cameras are mounted differently.
        here = dict(lat=FIELD[0], lon=FIELD[1], agl=60.0, heading=0.0)
        a = swarm.geolocate(obs(src='cruza'), state('cruza', **here))
        b = swarm.geolocate(obs(src='quadpi'), state('quadpi', **here))
        self.assertNotAlmostEqual(a['range_m'], b['range_m'], places=1)

    def test_unknown_source_falls_back_to_the_default_model(self):
        g = swarm.geolocate(obs(src='mystery'), state('mystery', agl=100.0))
        self.assertAlmostEqual(g['range_m'], 100/math.tan(math.radians(15)), places=3)


class RoundTripTests(unittest.TestCase):
    """Truth -> what the camera would report -> back to truth."""

    def round_trip(self, name, target, vehicle):
        model = swarm.sensor(name)
        record = swarmtest.observation_of(target, vehicle, model)
        self.assertIsNotNone(record, 'target should be in frame')
        store = ObservationStore()
        self.assertTrue(store.add(record, now=10.0, source=name))
        snap = store.snapshot(now=10.0)[0]
        g = swarm.geolocate(snap, vehicle)
        error, _ = swarm.distance_bearing(g['lat'], g['lon'],
                                          target['lat'], target['lon'])
        return error, g

    def test_cruza_round_trip_is_exact(self):
        v = state('cruza', agl=100.0, heading=90.0)
        lat, lon = swarm.project(FIELD[0], FIELD[1], 90.0,
                                 100/math.tan(math.radians(15)))
        error, _ = self.round_trip('cruza', {'lat': lat, 'lon': lon}, v)
        self.assertLess(error, 1.0)

    def test_round_trip_holds_off_boresight(self):
        v = state('cruza', agl=120.0, heading=215.0, pitch=-3.0)
        for bearing_offset in (-25.0, -10.0, 10.0, 25.0):
            with self.subTest(offset=bearing_offset):
                depression = 15.0+3.0-6.0
                rng = 120/math.tan(math.radians(depression))
                lat, lon = swarm.project(FIELD[0], FIELD[1],
                                         (215.0+bearing_offset) % 360, rng)
                error, _ = self.round_trip('cruza', {'lat': lat, 'lon': lon}, v)
                self.assertLess(error, 2.0)

    def test_target_outside_the_field_of_view_is_not_reported(self):
        v = state('cruza', agl=100.0, heading=0.0)
        behind = swarm.project(FIELD[0], FIELD[1], 180.0, 300.0)
        self.assertIsNone(swarmtest.observation_of(
            {'lat': behind[0], 'lon': behind[1]}, v, swarm.sensor('cruza')))

    def test_heading_error_moves_the_point_by_range_times_angle(self):
        v = state('cruza', agl=100.0, heading=0.0)
        rng = 100/math.tan(math.radians(15))
        lat, lon = swarm.project(FIELD[0], FIELD[1], 0.0, rng)
        record = swarmtest.observation_of({'lat': lat, 'lon': lon}, v,
                                          swarm.sensor('cruza'))
        store = ObservationStore()
        store.add(record, now=10.0, source='cruza')
        wrong = state('cruza', agl=100.0, heading=5.0)
        g = swarm.geolocate(store.snapshot(now=10.0)[0], wrong)
        error, _ = swarm.distance_bearing(g['lat'], g['lon'], lat, lon)
        self.assertAlmostEqual(error, rng*math.radians(5), delta=rng*0.01)


class FuseTests(unittest.TestCase):
    def cue_at(self, src, lat, lon, cls='person', score=0.8, oid=None):
        return {'id': oid or f'{src}/{cls}@0', 'src': src, 'cls': cls,
                'score': score, 'count': 1, 'last_seen_age': 1.0,
                'az_rel_deg': 0.0, 'el_rel_deg': 0.0, 'lat': lat, 'lon': lon,
                'bearing_deg': 90.0, 'range_m': 200.0, 'estimated': False}

    def test_two_aircraft_on_one_object_make_one_cross_cued_track(self):
        near = swarm.project(FIELD[0], FIELD[1], 0.0, 50.0)
        tracks = swarm.fuse([self.cue_at('cruza', *FIELD),
                             self.cue_at('quadpi', *near)])
        self.assertEqual(len(tracks), 1)
        self.assertTrue(tracks[0]['cross_cued'])
        self.assertEqual(tracks[0]['sources'], ['cruza', 'quadpi'])
        self.assertAlmostEqual(tracks[0]['span_m'], 50.0, delta=1.0)

    def test_objects_beyond_the_radius_stay_separate(self):
        far = swarm.project(FIELD[0], FIELD[1], 0.0, swarm.FUSE_RADIUS_M*3)
        tracks = swarm.fuse([self.cue_at('cruza', *FIELD),
                             self.cue_at('quadpi', *far)])
        self.assertEqual(len(tracks), 2)
        self.assertFalse(any(t['cross_cued'] for t in tracks))

    def test_different_classes_in_one_place_are_not_merged(self):
        tracks = swarm.fuse([self.cue_at('cruza', *FIELD, cls='person'),
                             self.cue_at('quadpi', *FIELD, cls='car')])
        self.assertEqual(len(tracks), 2)

    def test_a_bridging_cue_merges_two_clusters(self):
        a = FIELD
        b = swarm.project(a[0], a[1], 90.0, 200.0)
        middle = swarm.project(a[0], a[1], 90.0, 100.0)
        tracks = swarm.fuse([self.cue_at('cruza', *a, score=0.9, oid='a'),
                             self.cue_at('quadpi', *b, score=0.8, oid='b'),
                             self.cue_at('rn03', *middle, score=0.7, oid='c')],
                            radius_m=120)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['sources'], ['cruza', 'quadpi', 'rn03'])

    def test_unlocated_cues_survive_as_their_own_tracks(self):
        blind = self.cue_at('quadpi', None, None)
        blind['lat'] = blind['lon'] = None
        tracks = swarm.fuse([self.cue_at('cruza', *FIELD), blind])
        self.assertEqual(len(tracks), 2)
        unlocated = [t for t in tracks if not t['located']]
        self.assertEqual(len(unlocated), 1)
        self.assertIsNone(unlocated[0]['lat'])

    def test_cross_cued_tracks_sort_first(self):
        near = swarm.project(FIELD[0], FIELD[1], 0.0, 40.0)
        far = swarm.project(FIELD[0], FIELD[1], 0.0, 900.0)
        tracks = swarm.fuse([self.cue_at('cruza', *far, score=0.99, oid='solo'),
                             self.cue_at('cruza', *FIELD, score=0.5, oid='x'),
                             self.cue_at('rn03', *near, score=0.5, oid='y')])
        self.assertTrue(tracks[0]['cross_cued'])

    def test_track_id_names_its_contributing_cues(self):
        near = swarm.project(FIELD[0], FIELD[1], 0.0, 40.0)
        track = swarm.fuse([self.cue_at('cruza', *FIELD, oid='one'),
                            self.cue_at('rn03', *near, oid='two')])[0]
        self.assertEqual(set(track['id'].split('+')), {'one', 'two'})


class PictureTests(unittest.TestCase):
    def test_picture_geolocates_each_cue_with_its_own_aircraft(self):
        fleet = [state('cruza', agl=100.0, heading=0.0),
                 state('quadpi', agl=50.0, heading=180.0)]
        items = [obs(src='cruza'), obs(src='quadpi')]
        picture = swarm.picture(items, fleet)
        self.assertEqual(picture['sources'], ['cruza', 'quadpi'])
        north = [c for c in picture['cues'] if c['src'] == 'cruza'][0]
        south = [c for c in picture['cues'] if c['src'] == 'quadpi'][0]
        self.assertAlmostEqual(north['bearing_deg'], 0.0, places=6)
        self.assertAlmostEqual(south['bearing_deg'], 180.0, places=6)

    def test_a_cue_from_an_absent_aircraft_is_unlocated_not_misplaced(self):
        # The dangerous failure: resolving a quadpi cue with Cruza telemetry.
        picture = swarm.picture([obs(src='quadpi')],
                               [state('cruza', agl=100.0, heading=0.0)])
        self.assertIsNone(picture['cues'][0]['lat'])
        self.assertEqual(picture['cross_cued'], 0)

    def test_picture_counts_cross_cued_areas(self):
        # The two cameras are mounted at different angles, so put each aircraft
        # at the height that makes both boresights hit the same ground point -
        # otherwise the same bearing lands them 159 m apart, outside the radius.
        rn03_agl = 100/math.tan(math.radians(swarm.SENSORS['cruza']['pitch_down'])) \
            * math.tan(math.radians(swarm.SENSORS['rn03']['pitch_down']))
        fleet = [state('cruza', agl=100.0, heading=90.0),
                 state('rn03', agl=rn03_agl, heading=90.0)]
        items = [obs(src='cruza', oid='cruza/person@0'),
                 obs(src='rn03', oid='rn03/person@0')]
        picture = swarm.picture(items, fleet)
        self.assertEqual(picture['cross_cued'], 1)
        self.assertLess(picture['tracks'][0]['span_m'], 1.0)

    def test_the_same_bearing_from_differently_mounted_cameras_does_not_fuse(self):
        # The flip side, and a real trap: equal height and heading is not the
        # same look angle. An uncalibrated mount shows up as two tracks.
        fleet = [state('cruza', agl=100.0, heading=90.0),
                 state('rn03', agl=100.0, heading=90.0)]
        picture = swarm.picture([obs(src='cruza', oid='cruza/person@0'),
                                 obs(src='rn03', oid='rn03/person@0')], fleet)
        self.assertEqual(picture['cross_cued'], 0)
        self.assertEqual(len(picture['tracks']), 2)


class StoreSourceTests(unittest.TestCase):
    def record(self, az=0.0):
        return {'cls': 'person', 'score': 0.8, 'az_rel_deg': az,
                'el_rel_deg': -5.0, 'bbox': [0.2, 0.3, 0.1, 0.15]}

    def test_the_same_detection_from_two_aircraft_stays_two_entries(self):
        store = ObservationStore()
        store.add(self.record(), now=10.0, source='cruza')
        store.add(self.record(), now=10.0, source='quadpi')
        snap = store.snapshot(now=10.0)
        self.assertEqual(len(snap), 2)
        self.assertEqual({o['src'] for o in snap}, {'cruza', 'quadpi'})

    def test_a_record_cannot_claim_a_source(self):
        store = ObservationStore()
        spoof = dict(self.record(), src='rn03', source='rn03')
        store.add(spoof, now=10.0, source='quadpi')
        self.assertEqual(store.snapshot(now=10.0)[0]['src'], 'quadpi')

    def test_an_illegal_source_name_is_refused(self):
        store = ObservationStore()
        for bad in ('../etc', 'UPPER', 'a'*17, '', None, 5):
            self.assertFalse(store.add(self.record(), now=10.0, source=bad), bad)
        self.assertEqual(store.snapshot(now=10.0), [])

    def test_sources_lists_only_live_entries(self):
        store = ObservationStore(ttl=20)
        store.add(self.record(), now=10.0, source='cruza')
        store.add(self.record(), now=50.0, source='rn03')
        self.assertEqual(store.sources(now=50.0), ['rn03'])

    def test_the_fleet_wide_cap_still_holds(self):
        store = ObservationStore(max_entries=4)
        for i in range(30):
            store.add(self.record(az=float(i % 9*10-40)), now=10.0+i,
                      source=('cruza', 'quadpi', 'rn03')[i % 3])
        self.assertLessEqual(len(store.snapshot(now=40.0)), 4)


class HarnessTests(unittest.TestCase):
    def test_generated_records_are_wire_legal(self):
        v = state('cruza', agl=100.0, heading=0.0)
        rng = 100/math.tan(math.radians(15))
        lat, lon = swarm.project(FIELD[0], FIELD[1], 0.0, rng)
        record = swarmtest.observation_of({'lat': lat, 'lon': lon}, v,
                                          swarm.sensor('cruza'))
        wire = swarmtest.wire_check(record)
        self.assertTrue(wire['under_cap'] and wire['tap_framing']
                        and wire['validates'], wire)
        self.assertLess(wire['bytes'], 200)

    def test_wire_check_rejects_an_oversize_record(self):
        self.assertFalse(swarmtest.wire_check(
            {'cls': 'person', 'pad': 'x'*600})['under_cap'])

    def test_wrap180(self):
        for given, want in ((190, -170), (-190, 170), (0, 0), (180, -180)):
            self.assertAlmostEqual(swarmtest.wrap180(given), want)

    def test_run_chain_counts_what_the_store_kept(self):
        fleet = [state('cruza', agl=100.0, heading=0.0)]
        good = {'cls': 'person', 'score': 0.8, 'az_rel_deg': 0.0,
                'el_rel_deg': -2.0, 'bbox': [0.2, 0.3, 0.1, 0.1]}
        picture = swarmtest.run_chain([('cruza', good),
                                       ('cruza', {'cls': 'person'})], fleet)
        self.assertEqual(picture['_kept'], 1)
        self.assertEqual(picture['_offered'], 2)


class ParityTests(unittest.TestCase):
    """The browser's fallback maths must use the same constants as swarm.py.

    The panel prefers the server's positions, but its Cruza fallback is still
    live code. If these drift, the same cue moves depending on which build
    answered - exactly the kind of silent disagreement that makes an operator
    stop trusting the picture.
    """
    def setUp(self):
        self.js = (HERE.parent/'dashboard'/'dist'/'observations.js').read_text(
            encoding='utf-8')

    def constant(self, name):
        match = re.search(rf'const {name}\s*=\s*(-?[\d.]+)', self.js)
        self.assertIsNotNone(match, f'{name} not found in observations.js')
        return float(match.group(1))

    def test_cruza_mount_angles_match(self):
        self.assertEqual(self.constant('MOUNT_YAW_DEG'),
                         swarm.SENSORS['cruza']['yaw'])
        self.assertEqual(self.constant('MOUNT_PITCH_DOWN_DEG'),
                         swarm.SENSORS['cruza']['pitch_down'])

    def test_range_limits_match(self):
        self.assertEqual(self.constant('MAX_RANGE_M'), swarm.MAX_RANGE_M)
        self.assertEqual(self.constant('DEFAULT_RANGE_M'), swarm.DEFAULT_RANGE_M)

    def test_panel_will_not_place_another_aircrafts_cue_with_cruza_telemetry(self):
        self.assertIn("(obs.src || 'cruza') !== 'cruza'", self.js)


if __name__ == '__main__':
    unittest.main(verbosity=2)
