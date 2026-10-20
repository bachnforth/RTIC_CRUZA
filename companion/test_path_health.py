import importlib.util
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('path_health', Path(__file__).with_name('path-health.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
TARGET = dict(name='mesh', source_ip='10.223.79.20', peer_ip='10.223.58.11', network='10.223.0.0/16')


class Tests(unittest.TestCase):
    def test_no_source_no_probe(self):
        with patch.object(p, 'interface_for', return_value=None), patch.object(p.health, 'run') as run:
            self.assertEqual(p.probe(TARGET)['reason'], 'source_address_absent')
            run.assert_not_called()

    def test_wrong_route_never_probes_over_vpn(self):
        with patch.object(p, 'interface_for', return_value='eth0'), patch.object(p.health, 'read', return_value='0'), patch.object(p.health, 'run', return_value={'code': 0, 'text': '[{"dev":"tailscale0"}]'}) as run:
            self.assertEqual(p.probe(TARGET)['state'], 'unavailable')
            self.assertEqual(run.call_count, 1)

    def test_source_bound_probe_and_error_classification(self):
        for code, state in ((0, 'reachable'), (1, 'no_reply'), (2, 'unavailable'), (-1, 'unavailable')):
            with self.subTest(code=code), patch.object(p, 'interface_for', return_value='eth0'), patch.object(p.health, 'read', return_value='0'), patch.object(p.health, 'run', side_effect=[{'code': 0, 'text': '[{"dev":"eth0"}]'}, {'code': code, 'text': '64 bytes time=12.5 ms'}]) as run:
                self.assertEqual(p.probe(TARGET)['state'], state)
                self.assertEqual(run.call_args.args[0], ['ping', '-n', '-I', TARGET['source_ip'], '-c', '1', '-W', '2', TARGET['peer_ip']])

    def test_tracker_separates_unknown_from_no_reply(self):
        tracker = p.Tracker()
        tracker.update('reachable', 10)
        self.assertIsNone(tracker.update('reachable', 20))
        event = tracker.update('no_reply', 30)
        self.assertEqual(event['previous_observed_duration_s'], 20)
        event = tracker.update('unavailable', 40)
        self.assertEqual(event['previous'], 'no_reply')
        self.assertEqual(event['previous_observed_duration_s'], 10)

    def test_packet_metadata_and_unrelated_peer_filter(self):
        observer = p.Observer(threading.Event(), TARGET)
        ip = bytearray(20)
        ip[0], ip[9] = 0x45, 17
        ip[12:16], ip[16:20] = socket.inet_aton(TARGET['source_ip']), socket.inet_aton(TARGET['peer_ip'])
        body = b'private observation payload'
        packet = bytes(ip)+struct.pack('!HHHH', 45000, 17842, len(body)+8, 0)+body
        observer.packet(packet)
        ip[12:16] = socket.inet_aton('10.223.1.1')
        observer.packet(bytes(ip)+packet[20:])
        result = observer.snapshot()
        self.assertEqual(result['traffic']['tx_ip17']['packets'], 1)
        self.assertNotIn('private observation', json.dumps(result))

    def test_invalid_targets_rejected(self):
        for update in ({'peer_ip': '100.100.0.58'}, {'source_ip': '10.223.0.0'}, {'name': '../bad'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                p.validate(dict(node='quadpi', targets=[dict(TARGET, **update)]))

    def test_report_sessions_unknown_and_truncated_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'sample.jsonl'
            rows = [dict(kind='sample', session=session, node='quadpi', utc='2026-10-20T14:00:00+00:00', targets={'mesh': dict(state=state, rtt_ms=None)}) for session, state in [('boot1', 'reachable'), ('boot1', 'unavailable'), ('boot2', 'no_reply')]]
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows)+'{"kind":')
            result = p.report([path])['sessions']
            self.assertEqual(result['boot1']['targets']['mesh']['unavailable'], 1)
            self.assertEqual(result['boot1']['targets']['mesh']['no_reply'], 0)
            self.assertEqual(result['boot2']['samples'], 1)


if __name__ == '__main__':
    unittest.main()
