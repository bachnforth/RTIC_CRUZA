"""Offline checks of rotation, payload minimization and startup retry."""
import importlib.util
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('comms_health', Path(__file__).with_name('comms-health.py'))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Tests(unittest.TestCase):
    def test_rtp_metadata_only_and_unreachable(self):
        observer = c.Observer(threading.Event(), '100.100.0.57')
        ip = bytearray(20)
        ip[0], ip[9] = 0x45, 17
        ip[12:16], ip[16:20] = socket.inet_aton('100.100.0.58'), socket.inet_aton('100.100.0.57')
        for seq in (65535, 0):
            body = struct.pack('!BBHII', 128, 96, seq, 1234, 7)+b'private-camera-data'
            observer.packet(bytes(ip)+struct.pack('!HHHH', 12345, 5600, 8+len(body), 0)+body)
        result = observer.snapshot()
        self.assertEqual(result['video_rtp']['7']['packets'], 2)
        self.assertEqual(result['video_rtp']['7']['last_sequence_step'], 1)
        self.assertNotIn('private-camera', json.dumps(result))
        ip[9] = 1
        ip[12:16], ip[16:20] = ip[16:20], ip[12:16]
        observer.packet(bytes(ip)+bytes([3, 3])+bytes(6))
        self.assertEqual(observer.snapshot()['phone_icmp_unreachable'], 1)

    def test_rotation_and_low_disk_preserve_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root/'owner-notes.txt'
            unrelated.write_text('preserve')
            log = c.RotatingLog(root, {'session':'test'}, segment_bytes=100, total_bytes=650, reserve_bytes=0)
            for i in range(15):
                log.write({'sample':i, 'data':'x'*80})
            log.close()
            self.assertLessEqual(sum(p.stat().st_size for p in root.glob('comms-*.jsonl')),650)
            self.assertEqual(unrelated.read_text(),'preserve')
            for path in root.glob('comms-*.jsonl'):
                records = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(records[0]['kind'],'segment')
            with patch.object(c.shutil,'disk_usage', return_value=type('Usage',(),{'free':0})()):
                log.reserve_bytes=1
                self.assertFalse(log.write({'skipped':True}))
                self.assertEqual(log.skipped,1)

    def test_socket_failure_is_recorded_and_retried(self):
        stop = threading.Event()
        observer = c.Observer(stop, '100.100.0.57')
        calls=[]
        def fail(*args):
            calls.append(args)
            if len(calls)==2:stop.set()
            raise PermissionError()
        with patch.object(c.socket,'AF_PACKET',17,create=True), patch.object(c.socket,'socket',side_effect=fail), patch.object(stop,'wait',return_value=False):
            observer.loop()
        self.assertEqual(len(calls),2)
        self.assertEqual(observer.snapshot()['error'],'PermissionError')


if __name__ == '__main__':
    unittest.main()
