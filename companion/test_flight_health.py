"""Checks passive decoding and data minimization, without contacting hardware."""
import importlib.util
from pathlib import Path
import socket
import struct
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('health', Path(__file__).with_name('flight-health.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def packet(body, corrupt=False):
    header = bytes([253, len(body), 0, 0, 42, 1, 1, 0, 0, 0])
    frame = header + body + struct.pack('<H', h.crc(header[1:] + body, 50) ^ int(corrupt))
    ip = bytearray(20)
    ip[0], ip[9] = 0x45, 17
    ip[12:16], ip[16:20] = socket.inet_aton('100.100.0.58'), socket.inet_aton('100.100.0.57')
    return bytes(ip) + struct.pack('!HHHH', 14560, 14550, len(frame)+8, 0) + frame


class Tests(unittest.TestCase):
    def test_crc_and_disarmed_state(self):
        observer = h.Observer(threading.Event(), '100.100.0.57')
        observer.packet(packet(struct.pack('<IBBBBB', 10, 1, 3, 1, 3, 3)))
        result = observer.snapshot()
        hb = next(iter(result['heartbeats'].values()))
        self.assertFalse(hb['armed'])
        self.assertEqual(hb['custom_mode'], 10)
        self.assertTrue(hb['crc_valid'])
        observer.packet(packet(struct.pack('<IBBBBB', 10, 1, 3, 129, 3, 3), True))
        self.assertFalse(next(iter(observer.snapshot()['heartbeats'].values()))['armed'])
        self.assertEqual(observer.snapshot()['interval_udp_packets'], {})

    def test_no_sim_identifiers_retained(self):
        def fake(argv):
            if argv == ['mmcli', '-L']:
                return {'code': 0, 'text': '/Modem/0'}
            if argv[:3] == ['mmcli', '-m', '0']:
                return {'code': 0, 'text': 'modem.generic.state : connected\nmodem.3gpp.imei : secret-imei\nmodem.generic.equipment-identifier : secret-id'}
            return {'code': 0, 'text': '{}'}
        with patch.object(h, 'run', fake), patch.object(h, 'read', return_value=None):
            sample = h.sample('wwan0', '100.100.0.57', 0, False)
        # --signal-get API normally emits only modem.signal.*; require this prefix too.
        self.assertNotIn('secret', str(sample))


if __name__ == '__main__':
    unittest.main()
