import copy
import json
from pathlib import Path
import unittest
from cruza import tail_ip, router_text, usage_update


class Tests(unittest.TestCase):
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
