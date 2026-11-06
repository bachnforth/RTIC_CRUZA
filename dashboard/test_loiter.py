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
            if q.circle_known() and q.throttle_pwm() is not None and q.vehicle()['in_air'] is not None \
                    and 'MAV_GCS_SYSID' in q.params and 'WP_SPD' in q.params:
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

    def test_goto_land_flies_there_then_lands(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        entry = q.execute(dict(action='goto_land', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        self.assertTrue(entry['ok'], entry)
        self.assertIn('will land on arrival', entry['result'])
        repo = [m for m in bridge.received if m.get_type() == 'COMMAND_INT']
        self.assertEqual((repo[0].command, repo[0].x, repo[0].y, repo[0].z),
                         (mav.MAV_CMD_DO_REPOSITION, 350500000, -794900000, 15))
        self.assertEqual(q.status()['pending_land']['altitude_m'], 15)
        for _ in range(5):                                       # still on the way
            bridge.vehicle(**dict(FLYING, lat=35.0497, lon=-79.4900, alt=15))
            time.sleep(.2)
        self.assertEqual(self.modes_sent(bridge), [])
        for _ in range(15):        # arrives horizontally; height need not match
            bridge.vehicle(**dict(FLYING, lat=35.05001, lon=-79.49001, alt=11))
            time.sleep(.2)
            if self.modes_sent(bridge):
                break
        self.assertEqual(self.modes_sent(bridge), [control.LAND])
        self.assertIn('Arrived; landing', q.history[-1]['result'])
        self.assertIsNone(q.pending_land)

    def commands(self, bridge, kind='COMMAND_LONG'):
        return [m for m in bridge.received if m.get_type() == kind]

    def wait_for(self, bridge, check, **vehicle):
        for _ in range(20):
            bridge.vehicle(**vehicle)
            time.sleep(.2)
            if check():
                return True
        return False

    def test_goto_land_from_ground_climbs_to_50_m_before_travelling(self):
        bridge = FakeBridge()
        q = self.link(bridge, mode=0)                           # disarmed, STABILIZE, on the ground
        self.wait_for(bridge, lambda: 'WP_SPD' in q.params, mode=0)
        entry = q.execute(dict(action='goto_land', latitude=35.0500, longitude=-79.4900, altitude_m=30))
        self.assertTrue(entry['ok'], entry)
        self.assertEqual((entry['from_ground'], entry['takeoff_m']), (True, 50.0))
        self.assertIn('straight up to 50 m', entry['result'])
        sent = [(m.command, m.param1, m.param2, m.param7) for m in self.commands(bridge)]
        self.assertEqual(sent, [(mav.MAV_CMD_DO_SET_MODE, 1, control.GUIDED, 0),
                                (mav.MAV_CMD_COMPONENT_ARM_DISARM, 1, 0, 0),
                                (mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 50)])
        climbing = dict(FLYING, lat=35.0495395, lon=-79.4901843)
        # Still climbing: no horizontal travel yet, even at 48 m.
        for alt in (5, 25, 48):
            for _ in range(3):
                bridge.vehicle(**dict(climbing, alt=alt))
                time.sleep(.2)
        self.assertEqual(self.commands(bridge, 'COMMAND_INT'), [])
        self.assertTrue(q.status()['pending_land']['climbing'])
        # At 50 m: reposition to the point at 30 m, then 1.5 x WP_SPD.
        self.assertTrue(self.wait_for(bridge, lambda: self.commands(bridge, 'COMMAND_INT'), **dict(climbing, alt=49.6)))
        repo = self.commands(bridge, 'COMMAND_INT')[0]
        self.assertEqual((repo.x, repo.y, repo.z), (350500000, -794900000, 30))
        self.assertTrue(self.wait_for(bridge, lambda: len(self.commands(bridge)) == 4, **dict(climbing, alt=50)))
        speed = self.commands(bridge)[3]
        self.assertEqual((speed.command, speed.param1, speed.param2, speed.param3),
                         (mav.MAV_CMD_DO_CHANGE_SPEED, 1, 4.5, -1))
        self.assertIn('flying to the point at 4.5 m/s', q.history[-1]['result'])
        self.assertTrue(self.wait_for(bridge, lambda: self.modes_sent(bridge)[1:],
                                      **dict(FLYING, lat=35.0500, lon=-79.4900, alt=30)))
        self.assertEqual(self.modes_sent(bridge), [control.GUIDED, control.LAND])

    def test_goto_land_refused_when_armed_on_ground(self):
        bridge = FakeBridge()
        q = self.link(bridge, armed=True, mode=0)
        entry = q.execute(dict(action='goto_land', latitude=35.05, longitude=-79.49, altitude_m=15))
        self.assertIn('disarm first', entry['result'])
        self.assertEqual(bridge.received, [])

    def test_speed_change_not_accepted_is_not_fatal(self):
        class NoSpeedBridge(FakeBridge):
            def emit(self, message):        # the bridge drops DO_CHANGE_SPEED
                if message.get_type() == 'COMMAND_ACK' and message.command == mav.MAV_CMD_DO_CHANGE_SPEED:
                    return
                super().emit(message)
        bridge = NoSpeedBridge()
        q = self.link(bridge, **FLYING)
        self.wait_for(bridge, lambda: 'WP_SPD' in q.params, **FLYING)
        q.ack_timeout = .5
        entry = q.execute(dict(action='goto_land', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        self.assertTrue(entry['ok'], entry)
        self.assertIn('at the normal 3 m/s', entry['result'])
        self.assertIsNotNone(q.pending_land)

    def test_goto_land_cancelled_by_other_commands(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        q.execute(dict(action='goto_land', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        entry = q.execute(dict(action='hold'))
        self.assertTrue(entry.get('cancelled_pending_land'))
        for _ in range(5):
            bridge.vehicle(**dict(FLYING, mode=17, lat=35.0500, lon=-79.4900, alt=15))
            time.sleep(.2)
        self.assertEqual(self.modes_sent(bridge), [control.BRAKE])

    def test_pocket_mode_change_cancels_pending_land(self):
        bridge = FakeBridge()
        q = self.link(bridge, **FLYING)
        q.execute(dict(action='goto_land', latitude=35.0500, longitude=-79.4900, altitude_m=15))
        for _ in range(6):
            bridge.vehicle(**dict(FLYING, mode=5, lat=35.0500, lon=-79.4900, alt=15))
            time.sleep(.2)
        self.assertIsNone(q.pending_land)
        self.assertIn('Landing cancelled', q.history[-1]['result'])
        self.assertEqual(self.modes_sent(bridge), [])

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
