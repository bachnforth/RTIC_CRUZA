import tempfile
import threading
import time
import unittest
from pathlib import Path

import control
from fleet import mav
from test_control import FakeBridge

HOME = (35.0495395, -79.4901843)
REL = mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT


def item(seq, command, lat=0.0, lon=0.0, alt=0.0, frame=REL):
    return mav.MAVLink_mission_item_int_message(255, 0, seq, frame, command, 0, 1, 0, 0, 0, 0,
                                                int(round(lat*1e7)), int(round(lon*1e7)), alt, 0)


def mission(first=mav.MAV_CMD_NAV_TAKEOFF, far_lat=HOME[0]-0.0036, top=50.0):
    """Home, takeoff 30 m, a waypoint ~400 m south, then RTL."""
    return [item(0, mav.MAV_CMD_NAV_WAYPOINT, *HOME, 186.0, frame=mav.MAV_FRAME_GLOBAL_INT),
            item(1, first, HOME[0]-0.0005, HOME[1], 30.0),
            item(2, mav.MAV_CMD_DO_CHANGE_SPEED, 0, 0, 0, frame=mav.MAV_FRAME_MISSION),
            item(3, mav.MAV_CMD_NAV_WAYPOINT, far_lat, HOME[1], top),
            item(4, mav.MAV_CMD_NAV_RETURN_TO_LAUNCH, frame=mav.MAV_FRAME_MISSION)]


class MissionTests(unittest.TestCase):
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
        deadline = time.time()+15
        while time.time() < deadline:
            bridge.vehicle(**vehicle)
            if q.mission and 'MAV_GCS_SYSID' in q.params and q.vehicle()['online']:
                break
            time.sleep(.2)
        return q

    def sent(self, bridge):
        return [m.command for m in bridge.received]

    def test_mission_read_and_summarised(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge)
        m = q.status()['mission']
        self.assertTrue(m['known'])
        self.assertEqual((m['count'], m['first'], m['takeoff_m'], m['max_alt_m'], m['last']),
                         (5, 'NAV_TAKEOFF', 30.0, 50.0, 'NAV_RETURN_TO_LAUNCH'))
        self.assertAlmostEqual(m['farthest_m'], 400, delta=5)
        self.assertEqual(m['waypoints'], 2)
        # Reading is MISSION_REQUEST_* only: nothing was sent to change it.
        self.assertEqual(bridge.received, [])

    def test_launch_sends_arm_then_mission_start(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge, mode=0)
        entry = q.execute(dict(action='arm_mission', mission_signature=q.mission['signature']))
        self.assertTrue(entry['ok'], entry)
        self.assertEqual(self.sent(bridge), [mav.MAV_CMD_DO_SET_MODE, mav.MAV_CMD_COMPONENT_ARM_DISARM,
                                             mav.MAV_CMD_MISSION_START])
        start = bridge.received[-1]
        self.assertEqual((start.param1, start.param2), (0, 0))
        self.assertEqual(bridge.received[0].param2, control.GUIDED)
        self.assertEqual(entry['takeoff_m'], 30.0)

    def test_changed_mission_since_review_is_refused(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge)
        reviewed = q.mission['signature']
        bridge.mission = mission(top=40.0)          # someone uploads a different mission
        entry = q.execute(dict(action='arm_mission', mission_signature=reviewed))
        self.assertIn('changed since your review', entry['result'])
        self.assertEqual(bridge.received, [])
        self.assertEqual(q.mission['max_alt_m'], 40.0)  # and the summary is now current

    def test_failed_arm_never_starts_mission(self):
        bridge = FakeBridge(result=mav.MAV_RESULT_FAILED)
        bridge.mission = mission()
        q = self.link(bridge)
        self.assertFalse(q.execute(dict(action='arm_mission', mission_signature=q.mission['signature']))['ok'])
        self.assertNotIn(mav.MAV_CMD_MISSION_START, self.sent(bridge))

    def test_refused_missions(self):
        for kwargs, text in ((dict(first=mav.MAV_CMD_NAV_WAYPOINT), 'start with a takeoff'),
                             (dict(far_lat=HOME[0]-0.02), 'limit is 1500'),
                             (dict(top=150.0), 'limit is 120')):
            bridge = FakeBridge()
            bridge.mission = mission(**kwargs)
            q = self.link(bridge)
            self.assertIn(text, q.execute(dict(action='arm_mission',
                                               mission_signature=q.mission['signature']))['result'])
            self.assertEqual(bridge.received, [])

    def test_refused_when_armed_or_unread(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge, armed=True, landed=mav.MAV_LANDED_STATE_IN_AIR, alt=10)
        self.assertIn('Already armed', q.execute(dict(action='arm_mission'))['result'])
        q.mission = None
        bridge.vehicle()
        time.sleep(.3)
        self.assertIn('not read', q.execute(dict(action='arm_mission'))['result'])
        self.assertEqual(bridge.received, [])


if __name__ == '__main__':
    unittest.main()
