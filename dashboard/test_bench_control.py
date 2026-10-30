import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import control
from fleet import mav


class FakeBenchPort:
    """One-client TCP server playing the bench port + FC: replies to commands."""
    def __init__(self, result=mav.MAV_RESULT_ACCEPTED):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.result = result
        self.frames = []                 # every message the dashboard sent
        self.conn = None
        self.encoder = mav.MAVLink(None, srcSystem=1, srcComponent=1)
        self.stop = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()
        threading.Thread(target=self.vehicle, daemon=True).start()

    def emit(self, message):
        if self.conn:
            try:
                self.conn.sendall(message.pack(self.encoder))
            except OSError:
                pass

    def vehicle(self):
        while not self.stop.wait(.2):
            self.emit(mav.MAVLink_heartbeat_message(
                mav.MAV_TYPE_QUADROTOR, mav.MAV_AUTOPILOT_ARDUPILOTMEGA,
                mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 0, 3, 3))
            self.emit(mav.MAVLink_extended_sys_state_message(0, mav.MAV_LANDED_STATE_ON_GROUND))

    def run(self):
        self.server.settimeout(.2)
        parser = mav.MAVLink(None)
        while not self.stop.is_set():
            if self.conn is None:
                try:
                    self.conn, _ = self.server.accept()
                    self.conn.settimeout(.2)
                except socket.timeout:
                    continue
            try:
                data = self.conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                self.conn = None
                continue
            if not data:
                self.conn = None
                continue
            for m in parser.parse_buffer(data) or []:
                self.frames.append(m)
                if m.get_type() == 'COMMAND_LONG' and m.command == mav.MAV_CMD_COMPONENT_ARM_DISARM:
                    self.emit(mav.MAVLink_command_ack_message(m.command, self.result, 0, 0, 254, 190))


class BenchControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stop = threading.Event()

    def tearDown(self):
        self.stop.set()
        self.tmp.cleanup()

    def link(self, port):
        q = control.BenchControl(f'127.0.0.1:{port.port}', Path(self.tmp.name)/'log.jsonl',
                                 lambda: True, stop=self.stop)
        q.start()
        deadline = time.time()+5
        while time.time() < deadline and not (q.vehicle()['online'] and q.vehicle()['in_air'] is False):
            time.sleep(.05)
        return q

    def test_arm_and_disarm_use_gcs_254_190(self):
        port = FakeBenchPort()
        q = self.link(port)
        self.assertTrue(q.execute(dict(action='arm'))['ok'])
        arms = [m for m in port.frames if m.get_type() == 'COMMAND_LONG'
                and m.command == mav.MAV_CMD_COMPONENT_ARM_DISARM]
        self.assertEqual([(m.param1, m.param2) for m in arms], [(1, 0)])
        time.sleep(1.3)                  # heartbeats go out once a second
        self.assertTrue(all((m.get_srcSystem(), m.get_srcComponent()) == (254, 190) for m in port.frames))
        self.assertTrue(any(m.get_type() == 'HEARTBEAT' and m.type == mav.MAV_TYPE_GCS for m in port.frames))

    def test_only_arm_and_disarm_offered(self):
        port = FakeBenchPort()
        q = self.link(port)
        self.assertEqual([a['id'] for a in q.status()['actions']], ['arm', 'disarm'])
        for action in ('arm_takeoff', 'goto', 'rtl', 'land', 'hold'):
            self.assertIn('Not available', q.execute(dict(action=action))['result'])

    def test_telemetry_requests_match_bench_shapes(self):
        port = FakeBenchPort()
        q = self.link(port)
        q.request_telemetry()
        time.sleep(.3)
        self.assertFalse(any(m.get_type() == 'REQUEST_DATA_STREAM' for m in port.frames))
        intervals = [m for m in port.frames if m.get_type() == 'COMMAND_LONG'
                     and m.command == mav.MAV_CMD_SET_MESSAGE_INTERVAL]
        self.assertTrue(intervals)
        for m in intervals:
            self.assertIn(m.param1, control.BENCH_TELEMETRY)
            self.assertEqual((m.param2, m.param3, m.param4, m.param5, m.param6, m.param7),
                             (500000, 0, 0, 0, 0, 0))

    def test_refusal_reported(self):
        port = FakeBenchPort(result=mav.MAV_RESULT_DENIED)
        q = self.link(port)
        self.assertIn('Arm refused (DENIED)', q.execute(dict(action='arm'))['result'])

    def test_spec_parsing(self):
        self.assertEqual(control.parse_bench('100.100.0.10'), ('100.100.0.10', None))
        self.assertEqual(control.parse_bench('127.0.0.1:15760'), (None, 15760))
        with self.assertRaises(ValueError):
            control.BenchControl('10.0.0.5:15760', Path(self.tmp.name)/'x', lambda: False, stop=self.stop)


if __name__ == '__main__':
    unittest.main()
