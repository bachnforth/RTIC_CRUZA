import tempfile
import threading
import time
import unittest
from pathlib import Path

import control
from fleet import mav
from test_control import FakeBridge

FLYING = dict(armed=True, mode=4, landed=mav.MAV_LANDED_STATE_IN_AIR, alt=10)


class LoiterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stop = threading.Event()

    def tearDown(self):
        self.stop.set()
        self.tmp.cleanup()

    def link(self, bridge, **vehicle):
        q = control.QuadControl(bridge.sock.getsockname(), Path(self.tmp.name)/'log.jsonl',
                                lambda: True, stop=self.stop)
        q.start()
        deadline = time.time()+8
        while not bridge.peer and time.time() < deadline:
            time.sleep(.05)
        # Keep the fake vehicle talking so params and RC arrive.
        while time.time() < deadline:
            bridge.vehicle(**vehicle)
            if q.circle_known() and q.throttle_pwm() is not None and q.vehicle()['in_air'] is not None:
                break
            time.sleep(.2)
        return q

    def modes_sent(self, bridge):
        return [m.param2 for m in bridge.received if m.get_type() == 'COMMAND_LONG'
                and m.command == mav.MAV_CMD_DO_SET_MODE]

    def test_circle_settings_read_not_written(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        c = q.status()['circle']
        self.assertEqual((c['radius_m'], c['direction'], c['centred']), (10.0, 'clockwise', True))
        self.assertEqual(c['throttle_pwm'], 1500)
        self.assertFalse(any(m.get_type() == 'PARAM_SET' for m in bridge.received))

    def test_loiter_here_switches_to_circle(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        entry = q.execute(dict(action='loiter'))
        self.assertTrue(entry['ok'], entry)
        self.assertEqual(entry['centre'], 'current position')
        self.assertEqual(self.modes_sent(bridge), [control.CIRCLE])

    def test_loiter_refused_with_throttle_low_or_on_ground(self):
        bridge = FakeBridge()
        q = self.link(bridge, **dict(FLYING, throttle=1000))
        self.assertIn('centre it', q.execute(dict(action='loiter'))['result'])
        ground = FakeBridge()
        q2 = self.link(ground)
        self.assertIn('Take off first', q2.execute(dict(action='loiter'))['result'])
        self.assertEqual(bridge.received + ground.received, [])

    def test_loiter_at_point_flies_there_then_circles(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        target = dict(latitude=35.0500, longitude=-79.4900, altitude_m=15)
        entry = q.execute(dict(action='loiter', **target))
        self.assertTrue(entry['ok'], entry)
        self.assertIn('will circle on arrival', entry['result'])
        repo = [m for m in bridge.received if m.get_type() == 'COMMAND_INT']
        self.assertEqual((repo[0].x, repo[0].y, repo[0].z), (350500000, -794900000, 15))
        self.assertEqual(self.modes_sent(bridge), [])           # not circling yet
        for _ in range(15):                                      # arrive at the point
            bridge.vehicle(**dict(FLYING, lat=35.0500, lon=-79.4900, alt=15))
            time.sleep(.2)
            if self.modes_sent(bridge):
                break
        self.assertEqual(self.modes_sent(bridge), [control.CIRCLE])
        self.assertIn('Arrived; circling', q.history[-1]['result'])

    def test_any_command_cancels_pending_circle(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        q.execute(dict(action='loiter', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        self.assertIsNotNone(q.pending_circle)
        entry = q.execute(dict(action='rtl'))
        self.assertTrue(entry.get('cancelled_pending_circle'))
        self.assertIsNone(q.pending_circle)
        for _ in range(5):
            bridge.vehicle(**dict(FLYING, mode=6, lat=35.0500, lon=-79.4900, alt=15))
            time.sleep(.2)
        self.assertEqual(self.modes_sent(bridge), [control.RTL])

    def test_mode_change_elsewhere_cancels_pending_circle(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        q.execute(dict(action='loiter', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        for _ in range(6):                     # the Pocket switches to LOITER mid-way
            bridge.vehicle(**dict(FLYING, mode=5))
            time.sleep(.2)
        self.assertIsNone(q.pending_circle)
        self.assertIn('cancelled', q.history[-1]['result'])
        self.assertEqual(self.modes_sent(bridge), [])


if __name__ == '__main__':
    unittest.main()
