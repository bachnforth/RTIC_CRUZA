import tempfile
import threading
import time
import unittest
from pathlib import Path

import control
from fleet import mav
from test_control import FakeBridge
from test_mission import mission


class TfwDroneTests(unittest.TestCase):
    """TFW drone uses the same link and commands as quadpi under its own id."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stop = threading.Event()

    def tearDown(self):
        self.stop.set()
        self.tmp.cleanup()

    def link(self, bridge, **vehicle):
        q = control.QuadControl(bridge.sock.getsockname(), Path(self.tmp.name)/'tfw.jsonl',
                                lambda: True, stop=self.stop, name='rn03', title='TFW drone')
        q.start()
        deadline = time.time()+15
        while time.time() < deadline:
            bridge.vehicle(**vehicle)
            if q.mission and 'MAV_GCS_SYSID' in q.params and q.vehicle()['online']:
                break
            time.sleep(.2)
        return q

    def test_reports_as_tfw_drone(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge)
        self.assertEqual(q.snapshot()['name'], 'rn03')
        self.assertEqual([a['id'] for a in q.status()['actions']], [a['id'] for a in control.ACTION_INFO])
        self.assertEqual(q.status()['mission']['count'], 5)

    def test_same_launch_sequence(self):
        bridge = FakeBridge()
        bridge.mission = mission()
        q = self.link(bridge, mode=0)
        entry = q.execute(dict(action='arm_mission', mission_signature=q.mission['signature']))
        self.assertTrue(entry['ok'], entry)
        self.assertEqual([m.command for m in bridge.received],
                         [mav.MAV_CMD_DO_SET_MODE, mav.MAV_CMD_COMPONENT_ARM_DISARM, mav.MAV_CMD_MISSION_START])
        self.assertIn('"action": "arm_mission"', (Path(self.tmp.name)/'tfw.jsonl').read_text())

    def test_refusal_names_tfw_drone(self):
        bridge = FakeBridge()
        q = control.QuadControl(bridge.sock.getsockname(), Path(self.tmp.name)/'tfw.jsonl',
                                lambda: True, stop=self.stop, name='rn03', title='TFW drone')
        q.start()
        self.assertIn('No recent heartbeat from TFW drone', q.execute(dict(action='land'))['result'])
        self.assertEqual(bridge.received, [])


if __name__ == '__main__':
    unittest.main()
