"""Does /status really serve the shared observation picture?

Starts the dashboard's own HTTP handler in this process with stubbed links - no
MediaMTX, no SSH, no aircraft - and asks it for /status the way the browser
does. This catches the thing unit tests cannot: a name or key that only the real
handler touches.

Run: python swarm/test_status.py
"""
import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'dashboard'))
import server                       # noqa: E402
import swarm                        # noqa: E402
import swarmtest                    # noqa: E402

# The handler only answers requests whose Host is 127.0.0.1:8765, but it will
# answer them on any port. Bind an ephemeral one: a dashboard the user is
# actually running owns 8765, and on Windows a second bind there succeeds and
# then quietly loses every connection to the real one - which is a very
# convincing way to test the wrong program.
HOST_HEADER = '127.0.0.1:8765'
FIELD = (33.7235577, -85.9070862)


class FakeMedia:
    def poll(self):
        return None


class FakeFeed:
    def __init__(self, name):
        self.name = name

    def snapshot(self):
        return {'name': self.name, 'receiving': False, 'age_seconds': None,
                'bytes': 0, 'packets': 0, 'error': ''}

    def disconnect(self):
        pass


class FakeTelemetry:
    """Serves a fleet snapshot shaped like fleet.VehicleState.snapshot()."""
    def __init__(self, state):
        self.state = state

    def snapshot(self):
        return self.state

    def disconnect(self):
        pass


class FakeObserve:
    def __init__(self, name, records):
        self.name, self.records = name, records

    def snapshot(self):
        return {'name': self.name, 'host': 'stub', 'connected': True,
                'error': '', 'records': self.records}

    def disconnect(self):
        pass


class StatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Two aircraft looking at one point from different heights, each with
        # the mount angle its own camera really has.
        cruza = swarmtest.vehicle_state('cruza', *FIELD, 100.0, 90.0, 0.0)
        quad_point = swarm.project(*FIELD, 90.0, 40.0)
        quadpi = swarmtest.vehicle_state('quadpi', *quad_point, 60.0, 90.0, 0.0)
        target = swarm.project(
            *FIELD, 90.0,
            100/__import__('math').tan(__import__('math').radians(15)))
        truth = {'lat': target[0], 'lon': target[1], 'cls': 'person'}
        cls.truth = truth

        server.media = FakeMedia()
        server.feeds = [FakeFeed('cruza'), FakeFeed('quadpi'), FakeFeed('rn03')]
        server.telemetry = [FakeTelemetry(cruza), FakeTelemetry(quadpi)]
        server.observations = server.ObservationStore()
        kept = 0
        for name, state in (('cruza', cruza), ('quadpi', quadpi)):
            record = swarmtest.observation_of(truth, state, swarm.sensor(name))
            if record and server.observations.add(record, source=name):
                kept += 1
        cls.kept = kept
        server.observers = [FakeObserve('cruza', 1), FakeObserve('quadpi', 1),
                            FakeObserve('rn03', 0)]
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      kwargs={'poll_interval': 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(5)
        cls.httpd.server_close()
        server.STOP.set()

    def status(self):
        request = urllib.request.Request(
            f'http://127.0.0.1:{self.port}/status?watch=1',
            headers={'Host': HOST_HEADER,
                     'Sec-Fetch-Site': 'same-origin',
                     'Origin': 'http://127.0.0.1:8765'})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read())

    def test_both_aircraft_reported_into_the_store(self):
        self.assertEqual(self.kept, 2)

    def test_we_are_talking_to_our_own_handler(self):
        # Guards against the port race above: our stub names three readers and
        # a real dashboard does not.
        self.assertNotEqual(self.port, 8765)
        self.assertIn('readers', self.status()['observations'])

    def test_status_carries_the_swarm_picture(self):
        body = self.status()
        self.assertIn('swarm', body)
        self.assertEqual(body['swarm']['sources'], ['cruza', 'quadpi'])
        self.assertEqual(body['swarm']['fuse_radius_m'], swarm.FUSE_RADIUS_M)

    def test_the_two_reports_arrive_as_one_cross_cued_track(self):
        picture = self.status()['swarm']
        self.assertEqual(picture['cross_cued'], 1)
        track = picture['tracks'][0]
        self.assertEqual(track['sources'], ['cruza', 'quadpi'])
        self.assertEqual(len(track['contributors']), 2)
        error, _ = swarm.distance_bearing(track['lat'], track['lon'],
                                          self.truth['lat'], self.truth['lon'])
        self.assertLess(error, 5.0, f'fused point is {error:.1f} m off truth')

    def test_each_cue_names_the_aircraft_that_reported_it(self):
        body = self.status()
        self.assertEqual({c['src'] for c in body['swarm']['cues']},
                         {'cruza', 'quadpi'})
        self.assertEqual({o['src'] for o in body['observations']['items']},
                         {'cruza', 'quadpi'})

    def test_the_old_panel_fields_are_still_served(self):
        # The areas-of-interest panel reads these; a rename would blank it.
        payload = self.status()['observations']
        for key in ('connected', 'error', 'items'):
            self.assertIn(key, payload)
        self.assertTrue(payload['connected'])
        self.assertEqual([r['name'] for r in payload['readers']],
                         ['cruza', 'quadpi', 'rn03'])

    def test_status_is_json_serialisable_with_no_nan(self):
        raw = urllib.request.Request(
            f'http://127.0.0.1:{self.port}/status',
            headers={'Host': HOST_HEADER, 'Sec-Fetch-Site': 'none'})
        with urllib.request.urlopen(raw, timeout=5) as response:
            text = response.read().decode()
        self.assertNotIn('NaN', text)
        self.assertNotIn('Infinity', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
