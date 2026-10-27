"""Tests for the camera calibration tool.

The method is a round trip: build records from a camera with mount angles and a
field of view we chose, then check the tool recovers exactly those numbers. If
it cannot recover a known answer from clean data it has no business being
trusted on a morning's field data.

Run: python swarm/test_calibrate.py
"""
import argparse
import io
import json
import math
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'dashboard'))
import calibrate
import swarm
import swarmtest

TRUTH = {'lat': 33.7312, 'lon': -85.9151, 'cls': 'person'}


def synth(mount, count=20, agl=90.0, off_az=0.0, depression=None,
          config=None, start=1793000000.0, headings=None, stamp=True):
    """Records and a matching flight log for a camera with a known mount.

    config, when given, is the field of view the detector *believes*, so a
    mismatch with mount's real field of view simulates an uncalibrated lens the
    way observe.py would report it.

    stamp mirrors observe.py writing that believed field of view into each
    record. Pass stamp=False to simulate a capture taken before it did.
    """
    rows = []
    for i in range(count):
        pitch = 0.0
        down = mount['pitch_down']-pitch if depression is None else depression
        rng = agl/math.tan(math.radians(down))
        bearing = (i*37) % 360
        lat, lon = swarm.project(TRUTH['lat'], TRUTH['lon'], bearing, rng)
        _, to_target = swarm.distance_bearing(lat, lon, TRUTH['lat'], TRUTH['lon'])
        heading = ((headings[i % len(headings)] if headings
                    else to_target-mount['yaw']-off_az)) % 360
        state = swarmtest.vehicle_state('cruza', lat, lon, agl, heading, pitch)
        record = swarmtest.observation_of(TRUTH, state, mount, cls='person')
        if record is None:
            continue
        if config:
            cx = record['az_rel_deg']/mount['hfov']+0.5
            cy = 0.5-record['el_rel_deg']/mount['vfov']
            record['az_rel_deg'] = round((cx-0.5)*config['hfov'], 2)
            record['el_rel_deg'] = round((0.5-cy)*config['vfov'], 2)
        if stamp:
            believed = config or {'hfov': mount['hfov'], 'vfov': mount['vfov']}
            record['fov'] = [believed['hfov'], believed['vfov']]
        record['t'] = round(start+i, 2)
        rows.append((record, lat, lon, agl, heading, pitch))
    return rows


def write_pair(rows, directory, ground_amsl=150.0):
    """Write the records file and a .records.json log that matches it."""
    records = Path(directory)/'records.jsonl'
    with records.open('w', encoding='utf-8') as handle:
        for record, *_ in rows:
            handle.write(json.dumps(record)+'\n')
    gps, att = [], []
    for i, (record, lat, lon, agl, heading, pitch) in enumerate(rows):
        gps_seconds = record['t']-calibrate.GPS_EPOCH_UNIX+calibrate.GPS_UTC_LEAP_S
        week = int(gps_seconds//604800)
        gms = int(round((gps_seconds-week*604800)*1000))
        gps.append({'mavpackettype': 'GPS', 'TimeUS': i*1000000, 'Status': 3,
                    'GMS': gms, 'GWk': week, 'Lat': lat, 'Lng': lon,
                    'Alt': ground_amsl+agl, 'GCrs': heading})
        att.append({'mavpackettype': 'ATT', 'TimeUS': i*1000000,
                    'Pitch': pitch, 'Yaw': heading})
    log = Path(directory)/'log.records.json'
    log.write_text(json.dumps({'GPS': gps, 'ATT': att}))
    return records, log


def run(func, **kwargs):
    """Call a mode with argparse-style arguments, capturing its output."""
    defaults = dict(source='cruza', lat=TRUTH['lat'], lon=TRUTH['lon'],
                    log=None, aircraft_lat=None, aircraft_lon=None, agl=None,
                    heading=None, pitch=0.0, cls=None, min_score=0.0,
                    tolerance=calibrate.MATCH_TOLERANCE_S, ground_alt=None,
                    all_samples=False, reference_range=None, out=None,
                    yaw=None, pitch_down=None,
                    height=None, distance=None, offset=0.0, target_height=0.0)
    defaults.update(kwargs)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(argparse.Namespace(**defaults))
    return buffer.getvalue()


class TimeTests(unittest.TestCase):
    def test_gps_week_and_ms_convert_to_unix(self):
        # The 20 Oct flight's first fix, from the real log.
        unix = calibrate.gps_unix(2441, 243075300)
        self.assertAlmostEqual(unix, 1792524657.3, places=1)

    def test_a_week_is_a_week(self):
        self.assertAlmostEqual(
            calibrate.gps_unix(2442, 0)-calibrate.gps_unix(2441, 0), 604800)

    def test_leap_seconds_are_applied(self):
        self.assertAlmostEqual(calibrate.gps_unix(0, 0),
                               calibrate.GPS_EPOCH_UNIX-18)


class LogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.rows = synth({'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0,
                           'pitch_down': 15.0}, count=6)

    def test_height_above_ground_comes_off_the_lowest_sample(self):
        rows = list(self.rows)
        # Append a sample on the ground, as a real log would start.
        record, lat, lon, _, heading, pitch = rows[0]
        rows.append(({**record, 't': record['t']-10}, lat, lon, 0.0, heading, pitch))
        _, log = write_pair(rows, self.dir, ground_amsl=150.0)
        states = calibrate.log_states(log)
        self.assertAlmostEqual(min(s[3] for s in states), 0.0, places=3)
        self.assertAlmostEqual(max(s[3] for s in states), 90.0, places=3)

    def test_a_log_with_no_ground_sample_warns(self):
        _, log = write_pair(self.rows, self.dir, ground_amsl=150.0)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            calibrate.log_states(log)
        self.assertIn('may not contain the launch point', stderr.getvalue())

    def test_ground_alt_override_restores_the_real_height(self):
        _, log = write_pair(self.rows, self.dir, ground_amsl=150.0)
        states = calibrate.log_states(log, ground_alt=150.0)
        for state in states:
            self.assertAlmostEqual(state[3], 90.0, places=3)

    def test_nearest_state_respects_the_tolerance(self):
        states = [(100.0, 0, 0, 50, 0, 0), (110.0, 0, 0, 50, 0, 0)]
        self.assertEqual(calibrate.nearest_state(states, 100.4)[0], 100.0)
        self.assertEqual(calibrate.nearest_state(states, 109.8)[0], 110.0)
        self.assertIsNone(calibrate.nearest_state(states, 105.0))
        self.assertIsNone(calibrate.nearest_state([], 100.0))


class EstimateTests(unittest.TestCase):
    def state_for(self, agl=90.0, heading=0.0, pitch=0.0, rng=300.0, bearing=0.0):
        lat, lon = swarm.project(TRUTH['lat'], TRUTH['lon'], bearing, rng)
        return (0.0, lat, lon, agl, heading, pitch)

    def test_one_observation_recovers_both_mount_angles(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': -3.5, 'pitch_down': 21.0}
        rng = 90/math.tan(math.radians(21.0))
        state = self.state_for(agl=90.0, rng=rng, bearing=0.0,
                               heading=(180-mount['yaw']) % 360)
        vehicle = swarmtest.vehicle_state('cruza', state[1], state[2], state[3],
                                          state[4], state[5])
        record = swarmtest.observation_of(TRUTH, vehicle, mount)
        single = calibrate.estimate(record, state, TRUTH)
        self.assertAlmostEqual(single['yaw_est'], -3.5, places=1)
        self.assertAlmostEqual(single['pitch_down_est'], 21.0, places=1)
        self.assertTrue(single['centred'])

    def test_a_grounded_sample_is_rejected(self):
        record = {'az_rel_deg': 0.0, 'el_rel_deg': 0.0}
        self.assertIsNone(calibrate.estimate(record, self.state_for(agl=0.0), TRUTH))
        self.assertIsNone(calibrate.estimate(record, self.state_for(agl=0.2), TRUTH))

    def test_a_depression_outside_the_usable_band_is_rejected(self):
        record = {'az_rel_deg': 0.0, 'el_rel_deg': 0.0}
        # Far away and low: under 2 degrees of depression.
        self.assertIsNone(calibrate.estimate(
            record, self.state_for(agl=10.0, rng=5000.0), TRUTH))
        # Directly overhead: past 85 degrees.
        self.assertIsNone(calibrate.estimate(
            record, self.state_for(agl=500.0, rng=5.0), TRUTH))

    def test_a_target_under_the_aircraft_is_rejected(self):
        record = {'az_rel_deg': 0.0, 'el_rel_deg': 0.0}
        self.assertIsNone(calibrate.estimate(
            record, self.state_for(rng=0.2), TRUTH))

    def test_off_centre_samples_are_flagged(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 20.0}
        rng = 90/math.tan(math.radians(20.0))
        state = self.state_for(agl=90.0, rng=rng, heading=(180-20) % 360)
        vehicle = swarmtest.vehicle_state('cruza', *state[1:])
        record = swarmtest.observation_of(TRUTH, vehicle, mount)
        self.assertFalse(calibrate.estimate(record, state, TRUTH)['centred'])


class SummaryTests(unittest.TestCase):
    def test_summarise_reports_spread(self):
        s = calibrate.summarise([10.0, 12.0, 11.0])
        self.assertAlmostEqual(s['mean'], 11.0)
        self.assertEqual(s['n'], 3)
        self.assertAlmostEqual(s['median'], 11.0)
        self.assertGreater(s['stdev'], 0)

    def test_a_single_value_has_no_spread(self):
        self.assertEqual(calibrate.summarise([7.0])['stdev'], 0.0)

    def test_empty_is_none(self):
        self.assertIsNone(calibrate.summarise([]))

    def test_metres_at_is_range_times_radians(self):
        self.assertAlmostEqual(calibrate.metres_at(1.0, 660), 11.52, places=1)
        self.assertAlmostEqual(calibrate.metres_at(5.0, 660), 57.6, places=1)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp())/'r.jsonl'
        self.path.write_text(
            '# a comment\n'
            '\n'
            '{"cls":"person","score":0.9,"az_rel_deg":1,"el_rel_deg":-2}\n'
            '{"cls":"car","score":0.4,"az_rel_deg":3,"el_rel_deg":-4}\n'
            'not json at all\n'
            '{"cls":"person","score":0.2,"az_rel_deg":5,"el_rel_deg":-6}\n'
            '{"no_angles":true}\n'
            '[1,2,3]\n')

    def test_comments_blanks_and_junk_are_skipped(self):
        self.assertEqual(len(calibrate.load_records(self.path)), 3)

    def test_class_filter(self):
        got = calibrate.load_records(self.path, cls='person')
        self.assertEqual(len(got), 2)

    def test_score_filter(self):
        got = calibrate.load_records(self.path, min_score=0.5)
        self.assertEqual(len(got), 1)


class SolveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_solve_recovers_the_mount_from_a_flight_log(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': -3.5, 'pitch_down': 21.0}
        rows = synth(mount, count=20)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.solve, records=records, log=log, cls='person',
                  ground_alt=150.0)
        self.assertIn('mount yaw', out)
        self.assertRegex(out, r'mount yaw\s+-3\.50 deg')
        self.assertRegex(out, r'mount pitch_down\s+21\.00 deg')
        self.assertIn("'yaw': -3.5, 'pitch_down': 21.0", out)

    def test_solve_works_for_a_static_aircraft_with_no_log(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 28.0}
        # A camera on a mast: 3 m up, marker at the boresight ground point.
        rng = 3/math.tan(math.radians(28.0))
        lat, lon = swarm.project(TRUTH['lat'], TRUTH['lon'], 0.0, rng)
        _, to_target = swarm.distance_bearing(lat, lon, TRUTH['lat'], TRUTH['lon'])
        vehicle = swarmtest.vehicle_state('cruza', lat, lon, 3.0, to_target, 0.0)
        record = swarmtest.observation_of(TRUTH, vehicle, mount)
        path = Path(self.dir)/'static.jsonl'
        path.write_text(json.dumps({**record, 't': 1793000000.0})+'\n')
        out = run(calibrate.solve, records=path, aircraft_lat=lat,
                  aircraft_lon=lon, agl=3.0, heading=to_target)
        self.assertRegex(out, r'mount pitch_down\s+28\.0\d? deg')

    def test_a_single_heading_warns_about_compass_bias(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(mount, count=10, headings=[90.0])
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.solve, records=records, log=log, cls='person',
                  ground_alt=150.0)
        self.assertIn('includes any compass bias', out)

    def test_off_centre_only_data_warns_about_field_of_view(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(mount, count=10, off_az=20.0)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.solve, records=records, log=log, cls='person',
                  ground_alt=150.0)
        self.assertIn('frame centre', out)

    def test_too_few_samples_warns(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(mount, count=3)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.solve, records=records, log=log, cls='person',
                  ground_alt=150.0)
        self.assertIn('Collect 20 or more', out)

    def test_the_impact_is_quoted_in_metres(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 21.0}
        rows = synth(mount, count=20)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.solve, records=records, log=log, cls='person',
                  ground_alt=150.0, reference_range=660.0)
        self.assertIn('What this is worth at 660 m', out)
        # However far the measured mount is from the configured one, the tool
        # must quote that correction as range x angle-in-radians.
        delta = abs(21.0-swarm.SENSORS['cruza']['pitch_down'])
        self.assertIn(f'correcting pitch_down moves the point '
                      f'{calibrate.metres_at(delta, 660.0):7.1f} m', out)

    def test_no_usable_records_is_an_error_not_a_guess(self):
        path = Path(self.dir)/'empty.jsonl'
        path.write_text('')
        with self.assertRaises(SystemExit):
            run(calibrate.solve, records=path, aircraft_lat=0.0,
                aircraft_lon=0.0, agl=50.0, heading=0.0)

    def test_a_static_solve_without_a_state_refuses(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(mount, count=5)
        records, _ = write_pair(rows, self.dir)
        with self.assertRaises(SystemExit):
            run(calibrate.solve, records=records)

    def test_out_file_captures_the_samples(self):
        mount = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 2.0, 'pitch_down': 18.0}
        rows = synth(mount, count=20)
        records, log = write_pair(rows, self.dir)
        out_path = Path(self.dir)/'cal.json'
        run(calibrate.solve, records=records, log=log, cls='person',
            ground_alt=150.0, out=out_path)
        data = json.loads(out_path.read_text())
        self.assertAlmostEqual(data['suggested']['pitch_down'], 18.0, places=1)
        self.assertAlmostEqual(data['suggested']['yaw'], 2.0, places=1)
        self.assertEqual(len(data['samples']), data['used'])


class TapeTests(unittest.TestCase):
    """The ground calibration you can actually do with a tape measure."""

    def record_for(self, mount, height, distance, offset=0.0, pitch=0.0):
        """What the camera reports for a marker at a tape-measured spot."""
        ground_range = math.hypot(distance, offset)
        depression = math.degrees(math.atan2(height, ground_range))
        az_rel = math.degrees(math.atan2(offset, distance))-mount['yaw']
        el_rel = mount['pitch_down']-pitch-depression
        return {'cls': 'person', 'score': 0.9, 't': 1793000000.0,
                'az_rel_deg': round(az_rel, 2), 'el_rel_deg': round(el_rel, 2),
                'bbox': [0.4, 0.4, 0.1, 0.1]}

    def test_tape_estimate_recovers_the_mount(self):
        mount = {'yaw': -2.5, 'pitch_down': 18.0}
        record = self.record_for(mount, 1.40, 4.31)
        single = calibrate.tape_estimate(record, 1.40, 4.31)
        self.assertAlmostEqual(single['yaw_est'], -2.5, places=1)
        self.assertAlmostEqual(single['pitch_down_est'], 18.0, places=1)

    def test_a_lateral_offset_is_handled(self):
        mount = {'yaw': 0.0, 'pitch_down': 20.0}
        record = self.record_for(mount, 1.5, 4.0, offset=1.2)
        single = calibrate.tape_estimate(record, 1.5, 4.0, offset=1.2)
        self.assertAlmostEqual(single['yaw_est'], 0.0, places=1)
        self.assertAlmostEqual(single['pitch_down_est'], 20.0, places=1)

    def test_nose_alignment_makes_yaw_the_reported_azimuth_negated(self):
        # The whole point of sighting the nose at the marker: no compass needed.
        mount = {'yaw': 4.0, 'pitch_down': 15.0}
        record = self.record_for(mount, 1.5, 5.6)
        self.assertAlmostEqual(record['az_rel_deg'], -4.0, places=1)
        self.assertAlmostEqual(
            calibrate.tape_estimate(record, 1.5, 5.6)['yaw_est'], 4.0, places=1)

    def test_target_height_is_subtracted_from_the_camera_height(self):
        # The bias that would have ruined a ground calibration: a standing
        # person's box centre is about half their height up, and without that
        # correction pitch_down comes out roughly 10 deg wrong at these ranges.
        mount = {'yaw': 0.0, 'pitch_down': 15.0}
        record = self.record_for(mount, 1.20-0.85, 4.5)
        naive = calibrate.tape_estimate(record, 1.20, 4.5)
        corrected = calibrate.tape_estimate(record, 1.20, 4.5, target_height=0.85)
        self.assertAlmostEqual(corrected['pitch_down_est'], 15.0, places=1)
        self.assertGreater(abs(naive['pitch_down_est']-15.0), 9.0)

    def test_the_two_distance_cross_check_points_the_right_way(self):
        """The field procedure's recovery step, pinned so it cannot invert.

        CALIBRATION.md tells the operator which way to move --target-height
        based on whether the near or the far solve reads higher. Get that
        backwards and they walk the number away from the truth, so the direction
        is asserted here rather than reasoned about on a ladder.
        """
        camera, true_target, true_pitch_down = 2.60, 0.87, 21.0

        def reading(distance, assumed_target):
            effective = camera-true_target
            depression = math.degrees(math.atan2(effective, distance))
            record = {'az_rel_deg': 0.0,
                      'el_rel_deg': round(true_pitch_down-depression, 2)}
            return calibrate.tape_estimate(
                record, camera, distance, target_height=assumed_target
            )['pitch_down_est']

        # Correct assumption: both distances agree, and on the truth.
        self.assertAlmostEqual(reading(4.0, 0.87), true_pitch_down, places=1)
        self.assertAlmostEqual(reading(9.0, 0.87), true_pitch_down, places=1)

        # Assumed too LOW -> the near reading comes out HIGHER than the far.
        self.assertGreater(reading(4.0, 0.72), reading(9.0, 0.72))
        # Assumed too HIGH -> the near reading comes out LOWER than the far.
        self.assertLess(reading(4.0, 1.02), reading(9.0, 1.02))

        # And the near reading always moves further from truth than the far one.
        self.assertGreater(abs(reading(4.0, 0.72)-true_pitch_down),
                           abs(reading(9.0, 0.72)-true_pitch_down))

    def test_a_target_taller_than_the_camera_is_rejected(self):
        record = {'az_rel_deg': 0.0, 'el_rel_deg': 0.0}
        self.assertIsNone(
            calibrate.tape_estimate(record, 1.2, 4.5, target_height=1.5))

    def test_solve_warns_when_no_target_height_is_given(self):
        mount = {'yaw': 0.0, 'pitch_down': 15.0}
        directory = tempfile.mkdtemp()
        path = Path(directory)/'t.jsonl'
        with path.open('w', encoding='utf-8') as handle:
            for _ in range(6):
                handle.write(json.dumps(self.record_for(mount, 1.2, 4.5))+'\n')
        out = run(calibrate.solve, records=path, lat=None, lon=None,
                  height=1.2, distance=4.5)
        self.assertIn('Measure it', out)

    def test_an_impossible_tape_geometry_is_rejected(self):
        record = {'az_rel_deg': 0.0, 'el_rel_deg': 0.0}
        self.assertIsNone(calibrate.tape_estimate(record, 1.5, 0.0))
        self.assertIsNone(calibrate.tape_estimate(record, 0.2, 5.0))
        # 1.5 m up, 200 m out: under 2 degrees of depression, unusable.
        self.assertIsNone(calibrate.tape_estimate(record, 1.5, 200.0))

    def test_solve_in_tape_mode_recovers_the_mount(self):
        mount = {'yaw': -2.5, 'pitch_down': 18.0}
        directory = tempfile.mkdtemp()
        path = Path(directory)/'tape.jsonl'
        with path.open('w', encoding='utf-8') as handle:
            for _ in range(24):
                handle.write(json.dumps(self.record_for(mount, 1.40, 4.31))+'\n')
        out = run(calibrate.solve, records=path, lat=None, lon=None,
                  height=1.40, distance=4.31, reference_range=660.0)
        self.assertIn('Tape geometry: lens 1.40 m up', out)
        self.assertRegex(out, r'mount yaw\s+-2\.50 deg')
        self.assertRegex(out, r'mount pitch_down\s+18\.0\d? deg')
        self.assertIn('nose alignment replaces the compass', out)
        self.assertIn('2 cm of height error', out)

    def test_tape_mode_needs_both_numbers(self):
        directory = tempfile.mkdtemp()
        path = Path(directory)/'tape.jsonl'
        path.write_text(json.dumps(
            self.record_for({'yaw': 0.0, 'pitch_down': 15.0}, 1.5, 5.6))+'\n')
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.solve, records=path, lat=None, lon=None, height=1.5)
        self.assertIn('both --height and --distance', str(caught.exception))

    def test_no_geometry_at_all_refuses(self):
        directory = tempfile.mkdtemp()
        path = Path(directory)/'tape.jsonl'
        path.write_text(json.dumps(
            self.record_for({'yaw': 0.0, 'pitch_down': 15.0}, 1.5, 5.6))+'\n')
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.solve, records=path, lat=None, lon=None)
        self.assertIn('--lat/--lon', str(caught.exception))


class FovTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_fov_recovers_a_wrong_field_of_view(self):
        # The detector believes the CONFIGURED field of view, so take that from
        # SENSORS and make the real lens 1.2x wider; the tool should recover it
        # whatever the configured numbers happen to be.
        model = swarm.sensor('cruza')
        config = {'hfov': model['hfov'], 'vfov': model['vfov']}
        real = {'hfov': config['hfov']*1.2, 'vfov': config['vfov']*1.2,
                'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=16, agl=85.0, off_az=22.0, depression=28.0,
                     config=config)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.fov, records=records, log=log, cls='person',
                  ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        self.assertIn(f'hfov: configured {config["hfov"]:.1f} deg -> measured '
                      f'{real["hfov"]:.1f} deg', out)
        self.assertIn(f'vfov: configured {config["vfov"]:.1f} deg -> measured '
                      f'{real["vfov"]:.1f} deg', out)

    def test_a_correct_field_of_view_is_left_alone(self):
        model = swarm.sensor('cruza')
        config = {'hfov': model['hfov'], 'vfov': model['vfov']}
        real = {**config, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=16, agl=85.0, off_az=22.0, depression=28.0,
                     config=config)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.fov, records=records, log=log, cls='person',
                  ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        self.assertIn('leave it alone', out)

    def test_the_records_field_of_view_beats_the_table(self):
        # The mistake this exists to catch: SENSORS claims one field of view,
        # the aircraft flew with another. Measuring against the claim scales
        # the answer by exactly the disagreement, and the output looks
        # perfectly reasonable, so the records have to win.
        config = {'hfov': 66.0, 'vfov': 49.0}        # what the aircraft used
        real = {'hfov': 66.0, 'vfov': 52.3, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=16, agl=85.0, off_az=22.0, depression=28.0,
                     config=config)
        records, log = write_pair(rows, self.dir)
        saved = dict(swarm.SENSORS['cruza'])
        try:
            swarm.SENSORS['cruza']['vfov'] = 52.0    # an aspiration, not a config
            out = run(calibrate.fov, records=records, log=log, cls='person',
                      ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        finally:
            swarm.SENSORS['cruza'] = saved
        self.assertIn('Correct SENSORS to match the aircraft', out)
        self.assertIn('vfov: configured 49.0 deg -> measured 52.3 deg', out)
        # Measured against the 52.0 table it would have come out near 55.5.
        self.assertNotIn('measured 55.', out)

    def test_records_without_a_field_of_view_say_so(self):
        # A capture from before observe.py stamped the field: fall back to
        # SENSORS, but never quietly.
        model = swarm.sensor('cruza')
        config = {'hfov': model['hfov'], 'vfov': model['vfov']}
        real = {'hfov': config['hfov']*1.2, 'vfov': config['vfov']*1.2,
                'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=16, agl=85.0, off_az=22.0, depression=28.0,
                     config=config, stamp=False)
        records, log = write_pair(rows, self.dir)
        out = run(calibrate.fov, records=records, log=log, cls='person',
                  ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        self.assertIn('do not say what field of view produced them', out)
        self.assertIn(f'vfov: configured {config["vfov"]:.1f} deg', out)

    def test_a_capture_mixing_two_fields_of_view_is_refused(self):
        # One scale factor cannot describe two lenses; better to stop than to
        # average them into a number nobody can trace.
        config = {'hfov': 66.0, 'vfov': 49.0}
        real = {'hfov': 66.0, 'vfov': 52.3, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=16, agl=85.0, off_az=22.0, depression=28.0,
                     config=config)
        rows[-1][0]['fov'] = [66.0, 52.3]
        records, log = write_pair(rows, self.dir)
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.fov, records=records, log=log, cls='person',
                ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        self.assertIn('split the file', str(caught.exception))

    def test_tape_mode_recovers_a_vertical_field_of_view(self):
        # The case the field procedure actually needs: nobody measures a lens
        # from the air. Camera on the ladder, marker out and off to one side,
        # a real 52.3 deg lens reported through a 49.0 config.
        real = {'hfov': 66.0, 'vfov': 52.3}
        config = {'hfov': 66.0, 'vfov': 49.0}
        mount = {'yaw': 0.0, 'pitch_down': 25.0}
        height, distance, offset, box = 2.60, 5.50, 0.90, 0.87
        ground_range = math.hypot(distance, offset)
        depression = math.degrees(math.atan2(height-box, ground_range))
        az_true = math.degrees(math.atan2(offset, distance))-mount['yaw']
        el_true = mount['pitch_down']-depression
        rows = []
        for i in range(12):
            rows.append({'t': 1793000000.0+i, 'cls': 'person', 'score': 0.9,
                         'az_rel_deg': round(az_true*config['hfov']/real['hfov'], 2),
                         'el_rel_deg': round(el_true*config['vfov']/real['vfov'], 2),
                         'fov': [config['hfov'], config['vfov']],
                         'bbox': [0.4, 0.4, 0.1, 0.1]})
        records = Path(self.dir)/'tape.jsonl'
        records.write_text(''.join(json.dumps(r)+'\n' for r in rows),
                           encoding='utf-8')
        out = run(calibrate.fov, records=str(records), cls='person',
                  yaw=mount['yaw'], pitch_down=mount['pitch_down'],
                  height=height, distance=distance, offset=offset,
                  target_height=box)
        self.assertIn('Tape geometry', out)
        self.assertIn('vfov: configured 49.0 deg -> measured 52.3 deg', out)
        self.assertIn('hfov: configured 66.0 deg -> measured 66.0 deg', out)
        self.assertIn('leave it alone', out)   # hfov was already right

    def test_tape_mode_needs_both_tape_numbers(self):
        records = Path(self.dir)/'half.jsonl'
        records.write_text(json.dumps(
            {'t': 1.0, 'cls': 'person', 'score': 0.9, 'az_rel_deg': 10.0,
             'el_rel_deg': 8.0, 'bbox': [0.4, 0.4, 0.1, 0.1]})+'\n',
            encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.fov, records=str(records), cls='person',
                height=2.6, pitch_down=25.0)
        self.assertIn('both --height and --distance', str(caught.exception))

    def test_a_half_given_aircraft_state_is_refused_not_crashed(self):
        # --lat/--lon but no --log and no --heading used to reach
        # `args.heading % 360` and raise TypeError at the user.
        records = Path(self.dir)/'bare.jsonl'
        records.write_text(json.dumps(
            {'t': 1.0, 'cls': 'person', 'score': 0.9, 'az_rel_deg': 10.0,
             'el_rel_deg': 8.0, 'bbox': [0.4, 0.4, 0.1, 0.1]})+'\n',
            encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.fov, records=str(records), cls='person',
                pitch_down=25.0)
        message = str(caught.exception)
        self.assertIn('--heading', message)
        self.assertIn('tape geometry', message)

    def test_no_truth_point_and_no_tape_is_refused(self):
        records = Path(self.dir)/'notruth.jsonl'
        records.write_text(json.dumps(
            {'t': 1.0, 'cls': 'person', 'score': 0.9, 'az_rel_deg': 10.0,
             'el_rel_deg': 8.0, 'bbox': [0.4, 0.4, 0.1, 0.1]})+'\n',
            encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.fov, records=str(records), cls='person',
                lat=None, lon=None, pitch_down=25.0)
        self.assertIn('truth point', str(caught.exception))

    def test_centred_data_cannot_measure_a_field_of_view(self):
        real = {'hfov': 66.0, 'vfov': 49.0, 'yaw': 0.0, 'pitch_down': 15.0}
        rows = synth(real, count=10, off_az=0.0)
        records, log = write_pair(rows, self.dir)
        with self.assertRaises(SystemExit) as caught:
            run(calibrate.fov, records=records, log=log, cls='person',
                ground_alt=150.0, yaw=0.0, pitch_down=15.0)
        self.assertIn('off centre', str(caught.exception))


class CheckTests(unittest.TestCase):
    def test_check_finds_the_boresight_ground_point(self):
        # Derived from the configured mount, so recalibrating does not break it.
        down = swarm.SENSORS['cruza']['pitch_down']
        expected = 3.0/math.tan(math.radians(down))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            calibrate.check(argparse.Namespace(
                source='cruza', height=3.0, pitch=0.0, pitch_down=None,
                target_height=0.0, distances=[4, 8, expected, 20, 60]))
        out = buffer.getvalue()
        self.assertIn(f'meets the ground at {expected:.1f} m', out)
        self.assertIn('centred', out)

    def test_check_warns_when_no_target_height_is_given(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            calibrate.check(argparse.Namespace(
                source='cruza', height=1.2, pitch=0.0, pitch_down=None,
                target_height=0.0, distances=[4.5]))
        self.assertIn('half their', buffer.getvalue())

    def test_check_applies_the_target_height(self):
        # 1.2 m camera, box centre 0.85 m up: only 0.35 m of working height, so
        # the boresight meets the ground far closer in than it otherwise would.
        down = swarm.SENSORS['cruza']['pitch_down']
        near = 0.35/math.tan(math.radians(down))
        far = 1.2/math.tan(math.radians(down))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            calibrate.check(argparse.Namespace(
                source='cruza', height=1.2, pitch=0.0, pitch_down=None,
                target_height=0.85, distances=[near, 4.5]))
        out = buffer.getvalue()
        self.assertIn('0.35 m of working height', out)
        self.assertIn(f'meets the ground at {near:.1f} m', out)
        self.assertLess(near, far)  # the correction pulls the marker in

    def test_check_names_what_falls_outside_the_frame(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            calibrate.check(argparse.Namespace(
                source='cruza', height=3.0, pitch=0.0, pitch_down=None,
                target_height=0.0, distances=[0.5]))
        self.assertIn('outside the frame', buffer.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
