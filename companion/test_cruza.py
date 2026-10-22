import copy
import json
from pathlib import Path
import unittest
import signal
import tempfile
from unittest.mock import Mock, patch
from cruza import config, tail_ip, router_text, usage_update, video


class Tests(unittest.TestCase):
    def test_optional_mirror_preserves_original_video_destination(self):
        c = json.loads(Path('config.example.json').read_text())
        c.update(android_ip='100.100.0.57', video_max_seconds=0, video_mirror_port=15600)
        camera, stream = Mock(), Mock()
        camera.poll.return_value = stream.poll.return_value = None
        handlers = {}
        with patch('cruza.run', return_value={'code': 0}), \
             patch('cruza.subprocess.Popen', side_effect=[camera, stream]) as start, \
             patch('cruza.signal.signal', side_effect=lambda sig, handler: handlers.update({sig: handler})), \
             patch('cruza.time.sleep', side_effect=lambda _: handlers[signal.SIGTERM]()), \
             patch('cruza.emit'):
            video(c)
        pipeline = start.call_args_list[1].args[0]
        self.assertIn('multiudpsink', pipeline)
        self.assertIn('clients=100.100.0.57:5600,127.0.0.1:15600', pipeline)
        self.assertEqual(start.call_count, 2)  # One camera encoder, one packetizer.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'config.json'
            for port in (True, -1, 5600, 15599, 15610):
                c['video_mirror_port'] = port
                path.write_text(json.dumps(c))
                with self.assertRaises(ValueError):
                    config(path)

    def test_video_duration_validation(self):
        c = json.loads(Path('config.example.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for duration in (0, 1, 120, 7200):
                c['video_max_seconds'] = duration
                path.write_text(json.dumps(c))
                self.assertEqual(config(path)['video_max_seconds'], duration)
            for duration in (-1, 7201, True, 1.5, '0'):
                c['video_max_seconds'] = duration
                path.write_text(json.dumps(c))
                with self.assertRaises(ValueError):
                    config(path)

    def test_unlimited_video_runs_until_signal_and_closes_children(self):
        c = json.loads(Path('config.example.json').read_text())
        c.update(android_ip='100.100.0.57', video_max_seconds=0)
        camera, stream = Mock(), Mock()
        camera.poll.return_value = stream.poll.return_value = None
        handlers = {}
        with patch('cruza.run', return_value={'code': 0}), \
             patch('cruza.subprocess.Popen', side_effect=[camera, stream]), \
             patch('cruza.signal.signal', side_effect=lambda sig, handler: handlers.update({sig: handler})), \
             patch('cruza.time.sleep', side_effect=lambda _: handlers[signal.SIGTERM]()) as sleep, \
             patch('cruza.emit'):
            video(c)
        sleep.assert_called_once_with(1)
        for process in (camera, stream):
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)

    def test_public_endpoints_rejected(self):
        for ip in ('1.1.1.1', '10.229.125.15', '127.0.0.1', '::1', ''):
            with self.assertRaises(ValueError):
                tail_ip(ip)

    def test_private_router_no_public_tcp(self):
        c = json.loads(Path('config.example.json').read_text())
        c['android_ip'] = '100.100.0.50'
        text = router_text(c, '100.100.0.51')
        self.assertIn('TcpServerPort = 0', text)
        self.assertIn('Address = 100.100.0.51', text)
        self.assertNotIn('0.0.0.0', text)

    def test_usage_reboot_reset_and_day_boundaries(self):
        s = usage_update({}, 'wwan0', 100, 100, 'boot1', '2026-10-14')
        s = usage_update(s, 'wwan0', 150, 120, 'boot1', '2026-10-14')
        self.assertEqual(s['days']['2026-10-14'], {'rx': 50, 'tx': 20})
        s = usage_update(s, 'wwan0', 3, 4, 'boot2', '2026-10-15')
        self.assertEqual(s['days']['2026-10-15'], {'rx': 0, 'tx': 0})
        s = usage_update(s, 'wwan0', 13, 14, 'boot2', '2026-10-15')
        self.assertEqual(s['days']['2026-10-15'], {'rx': 10, 'tx': 10})
        s = usage_update(s, 'wwan0', 1, 1, 'boot2', '2026-10-15')
        self.assertEqual(s['days']['2026-10-15'], {'rx': 10, 'tx': 10})


if __name__ == '__main__':
    unittest.main()
