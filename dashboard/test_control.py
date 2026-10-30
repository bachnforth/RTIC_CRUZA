import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import control
from fleet import mav


class FakeBridge:
    """Plays the Pi bridge + FC: replies to commands with a fixed result."""
    def __init__(self, result=mav.MAV_RESULT_ACCEPTED, reply=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.settimeout(.2)
        self.result, self.reply = result, reply
        self.received = []
        self.peer = None
        self.encoder = mav.MAVLink(None, srcSystem=1, srcComponent=1)
        self.stop = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def emit(self, message):
        if self.peer:
            self.sock.sendto(message.pack(self.encoder), self.peer)

    # The FC's own circle settings, answered to PARAM_REQUEST_READ.
    params = {'CIRCLE_RADIUS_M': 10.0, 'CIRCLE_RATE': 20.0, 'CIRCLE_OPTIONS': 5.0, 'RCMAP_THROTTLE': 3.0,
              'MAV_GCS_SYSID': 255.0}
    mission = []                    # MISSION_ITEM_INT messages served on request

    def vehicle(self, armed=False, mode=4, landed=mav.MAV_LANDED_STATE_ON_GROUND, alt=0.0,
                lat=35.0495395, lon=-79.4901843, throttle=1500):
        self.emit(mav.MAVLink_heartbeat_message(
            mav.MAV_TYPE_QUADROTOR, mav.MAV_AUTOPILOT_ARDUPILOTMEGA,
            mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | (mav.MAV_MODE_FLAG_SAFETY_ARMED if armed else 0),
            mode, 4, 3))
        self.emit(mav.MAVLink_global_position_int_message(
            0, int(round(lat*1e7)), int(round(lon*1e7)), 100000, int(alt*1000), 0, 0, 0, 0))
        self.emit(mav.MAVLink_extended_sys_state_message(0, landed))
        self.emit(mav.MAVLink_rc_channels_message(0, 8, 1500, 1500, throttle, 1500, *([1500]*14), 255))

    def run(self):
        parser = mav.MAVLink(None)
        while not self.stop.is_set():
            try:
                data, self.peer = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            for m in parser.parse_buffer(data) or []:
                if m.get_type() == 'MISSION_REQUEST_LIST':
                    self.emit(mav.MAVLink_mission_count_message(255, 0, len(self.mission), 0))
                if m.get_type() == 'MISSION_REQUEST_INT' and m.seq < len(self.mission):
                    self.emit(self.mission[m.seq])
                if m.get_type() == 'PARAM_REQUEST_READ' and m.param_id in self.params:
                    self.emit(mav.MAVLink_param_value_message(
                        m.param_id.encode(), self.params[m.param_id], mav.MAV_PARAM_TYPE_REAL32, 999, 0))
                # Stream setup from the link's heartbeat loop is not a flight command.
                if m.get_type() in ('COMMAND_LONG', 'COMMAND_INT') and m.command != mav.MAV_CMD_SET_MESSAGE_INTERVAL:
                    self.received.append(m)
                    if self.reply:
                        self.emit(mav.MAVLink_command_ack_message(m.command, self.result, 0, 0, 255, 190))


class ControlTests(unittest.TestCase):
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
        # The first heartbeat from the laptop lets the fake bridge reply.
        deadline = time.time()+3
        while not bridge.peer and time.time() < deadline:
            time.sleep(.05)
        bridge.vehicle(**vehicle)
        deadline = time.time()+8
        while time.time() < deadline:
            v = q.vehicle()
            if v['online'] and v['position'] and v['in_air'] is not None and 'MAV_GCS_SYSID' in q.params:
                break
            if not v['online']:
                bridge.vehicle(**vehicle)
            time.sleep(.05)
        return q

    def test_arm_takeoff_sends_arm_then_takeoff(self):
        bridge = FakeBridge()
        q = self.link(bridge)
        entry = q.execute(dict(action='arm_takeoff', altitude_m=15))
        self.assertTrue(entry['ok'], entry)
        cmds = [(m.command, m.param1, m.param2, m.param7) for m in bridge.received]
        self.assertEqual(cmds, [(mav.MAV_CMD_COMPONENT_ARM_DISARM, 1, 0, 0),
                                (mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 15)])
        self.assertIn('arm_takeoff', (Path(self.tmp.name)/'log.jsonl').read_text())

    def test_arm_only_sends_one_unforced_arm_and_no_mode_change(self):
        bridge = FakeBridge()
        q = self.link(bridge, mode=0)
        entry = q.execute(dict(action='arm'))
        self.assertTrue(entry['ok'], entry)
        self.assertEqual(entry['mode'], 'STABILIZE')
        self.assertEqual([(m.command, m.param1, m.param2) for m in bridge.received],
                         [(mav.MAV_CMD_COMPONENT_ARM_DISARM, 1, 0)])

    def test_arm_only_refused_outside_pilot_modes(self):
        for mode, name in ((3, 'AUTO'), (4, 'GUIDED'), (6, 'RTL'), (9, 'LAND')):
            bridge = FakeBridge()
            q = self.link(bridge, mode=mode)
            self.assertIn(f'Mode is {name}', q.execute(dict(action='arm'))['result'])
            self.assertEqual(bridge.received, [])

    def test_arm_only_refused_when_already_armed(self):
        bridge = FakeBridge()
        q = self.link(bridge, armed=True)
        self.assertIn('Already armed', q.execute(dict(action='arm'))['result'])
        self.assertEqual(bridge.received, [])

    def test_takeoff_from_other_mode_switches_to_guided_first(self):
        bridge = FakeBridge()
        q = self.link(bridge, mode=5)
        self.assertTrue(q.execute(dict(action='arm_takeoff', altitude_m=10))['ok'])
        self.assertEqual(bridge.received[0].command, mav.MAV_CMD_DO_SET_MODE)
        self.assertEqual(bridge.received[0].param2, 4)

    def test_refusal_stops_the_sequence(self):
        bridge = FakeBridge(result=mav.MAV_RESULT_FAILED)
        q = self.link(bridge)
        entry = q.execute(dict(action='arm_takeoff', altitude_m=10))
        self.assertFalse(entry['ok'])
        self.assertIn('Arm refused (FAILED)', entry['result'])
        self.assertEqual(len(bridge.received), 1)

    def test_adopts_fc_gcs_id_and_waits_for_it(self):
        bridge = FakeBridge()
        bridge.params = dict(bridge.params, MAV_GCS_SYSID=254.0)
        q = self.link(bridge, mode=0)
        self.assertEqual(q.status()['gcs_id'], 254)
        bridge.received.clear()
        q.execute(dict(action='arm'))
        self.assertEqual([m.get_srcSystem() for m in bridge.received], [254])
        unknown = FakeBridge()
        unknown.params = {k: v for k, v in unknown.params.items() if k != 'MAV_GCS_SYSID'}
        q2 = control.QuadControl(unknown.sock.getsockname(), Path(self.tmp.name)/'l2', lambda: True,
                                 stop=self.stop)
        q2.start()
        deadline = time.time()+3
        while not unknown.peer and time.time() < deadline:
            time.sleep(.05)
        unknown.vehicle(mode=0)
        time.sleep(.5)
        self.assertIn('GCS system id not read', q2.execute(dict(action='arm'))['result'])
        self.assertEqual(unknown.received, [])

    def test_refusal_reason_arriving_after_ack_is_included(self):
        bridge = FakeBridge(result=mav.MAV_RESULT_FAILED)
        q = self.link(bridge, mode=0)
        original = bridge.emit
        def emit_late_reason(message):
            original(message)
            if message.get_type() == 'COMMAND_ACK':
                time.sleep(.2)
                original(mav.MAVLink_statustext_message(2, b'PreArm: Need Position Estimate'))
        bridge.emit = emit_late_reason
        self.assertIn('Need Position Estimate', q.execute(dict(action='arm'))['result'])

    def test_no_reply_is_reported_and_not_retried(self):
        bridge = FakeBridge(reply=False)
        q = self.link(bridge, armed=True, landed=mav.MAV_LANDED_STATE_IN_AIR, alt=10)
        entry = q.execute(dict(action='rtl'))
        self.assertFalse(entry['ok'])
        self.assertIn('no reply', entry['result'])
        self.assertEqual(len(bridge.received), 1)

    def test_goto_sends_exact_reposition(self):
        bridge = FakeBridge()
        q = self.link(bridge, armed=True, landed=mav.MAV_LANDED_STATE_IN_AIR, alt=10)
        entry = q.execute(dict(action='goto', latitude=35.0500, longitude=-79.4900, altitude_m=20))
        self.assertTrue(entry['ok'], entry)
        m = bridge.received[0]
        self.assertEqual((m.command, m.frame, m.param1, m.param2, m.x, m.y, m.z),
                         (mav.MAV_CMD_DO_REPOSITION, mav.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                          -1, 1, 350500000, -794900000, 20))

    def test_local_guards(self):
        bridge = FakeBridge()
        ground = self.link(bridge)
        cases = [
            (dict(action='arm_takeoff', altitude_m=0), 'between'),
            (dict(action='arm_takeoff', altitude_m=500), 'between'),
            (dict(action='arm_takeoff', altitude_m='10'), 'number'),
            (dict(action='goto', latitude=35.05, longitude=-79.49, altitude_m=20), 'Take off first'),
            (dict(action='flip'), 'Not available'),
        ]
        for body, text in cases:
            entry = ground.execute(body)
            self.assertFalse(entry['ok'])
            self.assertIn(text, entry['result'])
        self.assertEqual(bridge.received, [])

    def test_goto_distance_limit_and_no_disarm_in_air(self):
        bridge = FakeBridge()
        q = self.link(bridge, armed=True, landed=mav.MAV_LANDED_STATE_IN_AIR, alt=10)
        self.assertIn('limit', q.execute(dict(action='goto', latitude=35.10, longitude=-79.49, altitude_m=20))['result'])
        self.assertIn('Refusing to disarm', q.execute(dict(action='disarm'))['result'])
        self.assertEqual(bridge.received, [])

    def test_nothing_sent_without_heartbeat(self):
        bridge = FakeBridge()
        q = control.QuadControl(bridge.sock.getsockname(), Path(self.tmp.name)/'log.jsonl',
                                lambda: False, stop=self.stop)
        self.assertIn('No recent heartbeat', q.execute(dict(action='rtl'))['result'])


if __name__ == '__main__':
    unittest.main()
