import base64
import json
import tempfile
import unittest
from pathlib import Path

import swarm
from handover import APPROVE_MAX_AGE_S, KEEP_DECIDED_S, PENDING_TTL_S, HandoverQueue
from handover_intake import CHIP_MAX_BYTES, CHIP_PART_CHARS, ChipAssembler, Intake, is_chip

JPEG = b'\xff\xd8\xff\xe0' + bytes(range(256)) * 8 + b'\xff\xd9'


def parts(seq, jpeg=JPEG, size=CHIP_PART_CHARS):
    text = base64.b64encode(jpeg).decode()
    # Split on 4-character boundaries so each part decodes on its own.
    size -= size % 4
    chunks = [text[i:i+size] for i in range(0, len(text), size)]
    return [{'t': 1.0, 'chip': seq, 'part': i, 'parts': len(chunks), 'jpg': c}
            for i, c in enumerate(chunks)]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def cue(cid='cruza/person@0', lat=32.6, lon=-85.5, cls='person', score=0.8, src='cruza', count=1):
    return {'id': cid, 'src': src, 'cls': cls, 'score': score, 'count': count,
            'lat': lat, 'lon': lon, 'range_m': 200.0, 'bearing_deg': 90.0, 'estimated': False}


class ChipTests(unittest.TestCase):
    def test_parts_fit_the_tap_cap_and_reassemble(self):
        chips = ChipAssembler()
        for p in parts(7):
            self.assertTrue(is_chip(p))
            self.assertLessEqual(len(json.dumps(p).encode()), 512)
            self.assertTrue(chips.add(p, now=1, source='cruza'))
        self.assertEqual(chips.find('cruza', [5, 6, 7], now=2), JPEG)
        self.assertIsNone(chips.find('quadpi', [7], now=2))   # another aircraft's seq 7

    def test_out_of_order_parts(self):
        chips = ChipAssembler()
        for p in reversed(parts(3)):
            chips.add(p, now=1, source='cruza')
        self.assertEqual(chips.find('cruza', [3], now=1), JPEG)

    def test_rejects_bad_parts_and_bad_images(self):
        chips = ChipAssembler()
        good = parts(1)[0]
        for bad in ({**good, 'jpg': '***'}, {**good, 'part': good['parts']},
                    {**good, 'parts': 0}, {**good, 'chip': -1}, {**good, 'part': True},
                    {**good, 'jpg': 'A' * (CHIP_PART_CHARS + 4)}):
            self.assertFalse(chips.add(bad, now=1, source='cruza'))
        self.assertFalse(chips.add(good, now=1, source='Not Valid!'))
        # Well-formed parts that are not a JPEG are discarded once complete.
        for p in parts(2, jpeg=b'GIF89a' + b'x' * 600):
            chips.add(p, now=1, source='cruza')
        self.assertIsNone(chips.find('cruza', [2], now=1))
        big = b'\xff\xd8\xff' + b'x' * CHIP_MAX_BYTES + b'\xff\xd9'
        for p in parts(4, jpeg=big, size=CHIP_PART_CHARS)[:64]:
            chips.add(p, now=1, source='cruza')
        self.assertIsNone(chips.find('cruza', [4], now=1))

    def test_unfinished_chip_expires(self):
        chips = ChipAssembler()
        ps = parts(9)
        for p in ps[:-1]:
            chips.add(p, now=1, source='cruza')
        chips.add(ps[-1], now=100, source='cruza')   # first parts expired meanwhile
        self.assertIsNone(chips.find('cruza', [9], now=100))

    def test_intake_passes_detections_through_and_maps_chips(self):
        intake = Intake()
        rec = {'cls': 'person', 'score': .7, 'az_rel_deg': 1, 'el_rel_deg': -3,
               'bbox': [.1, .1, .2, .2], 'seq': 41}
        self.assertTrue(intake.add(rec, now=1, source='cruza'))
        self.assertTrue(intake.add({**rec, 'seq': 'x'}, now=2, source='cruza'))
        for p in parts(41):
            self.assertTrue(intake.add(p, source='cruza'))
        [item] = intake.snapshot(now=2)          # the store's own snapshot, unchanged
        self.assertEqual(item['count'], 2)
        self.assertNotIn('seqs', item)
        self.assertEqual(intake.image_for({'id': item['id'], 'src': 'cruza'}), JPEG)
        self.assertIsNone(intake.image_for({'id': item['id'], 'src': 'quadpi'}))
        self.assertFalse(intake.add({'cls': 'bad!'}, source='cruza'))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.clock = Clock()
        root = Path(self.dir.name)
        self.log = root/'handover.log'
        self.q = HandoverQueue(self.log, root/'images', clock=self.clock, wall=lambda: 1.8e9)

    def tearDown(self):
        self.dir.cleanup()

    def entries(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_cue_becomes_one_pending_request_and_nearby_cues_merge(self):
        self.q.sync([cue()])
        # Same class 40 m away from a different azimuth bucket: same request.
        lat2, lon2 = swarm.project(32.6, -85.5, 45, 40)
        self.q.sync([cue('cruza/person@3', lat2, lon2, count=4)])
        # Different class at the same spot: a separate request.
        self.q.sync([cue('cruza/car@0', cls='car')])
        snap = self.q.snapshot()
        self.assertEqual(len(snap), 2)
        person = next(r for r in snap if r['cls'] == 'person')
        self.assertEqual((person['status'], person['sightings']), ('pending', 5))
        self.assertAlmostEqual(person['lat'], lat2)

    def test_stale_cue_is_not_placed(self):
        # A cue last seen 9 s ago was re-placed with current telemetry; ignore it.
        self.q.sync([{**cue(), 'last_seen_age': 9.0}])
        self.assertEqual(self.q.snapshot(), [])

    def test_unlocated_cue_is_not_offered(self):
        self.q.sync([cue(lat=None, lon=None)])
        self.assertEqual(self.q.snapshot(), [])

    def test_image_attaches_from_matching_record_numbers(self):
        self.q.sync([cue()], lambda c: JPEG if c['id'] == 'cruza/person@0' else None)
        r = self.q.snapshot()[0]
        self.assertEqual(r['image_rev'], 1)
        self.assertEqual(self.q.image(r['id']), JPEG)

    def test_approve_freezes_position_and_logs_with_image(self):
        self.q.sync([cue()], lambda c: JPEG)
        rid = self.q.snapshot()[0]['id']
        ok, msg, _ = self.q.decide(rid, 'approve', target='cruza', live=('quadpi',))
        self.assertFalse(ok)
        self.assertIn('cannot take a handover', msg)
        ok, _, r = self.q.decide(rid, 'approve', target='quadpi', live=('quadpi',))
        self.assertEqual(r['decision']['mode'], 'live')
        self.assertTrue(ok)
        self.assertEqual(r['decision']['target'], 'quadpi')
        self.assertEqual((r['decision']['lat'], r['decision']['lon']), (32.6, -85.5))
        # Later sightings nearby do not move an approved request or open a new one.
        lat2, lon2 = swarm.project(32.6, -85.5, 0, 50)
        self.q.sync([cue('cruza/person@2', lat2, lon2)])
        snap = self.q.snapshot()
        self.assertEqual(len(snap), 1)
        self.assertEqual((snap[0]['lat'], snap[0]['status']), (32.6, 'approved'))
        ok, msg, _ = self.q.decide(rid, 'deny')
        self.assertFalse(ok)
        [entry] = self.entries()
        self.assertEqual((entry['outcome'], entry['target'], entry['cls']), ('approved', 'quadpi', 'person'))
        self.assertEqual((Path(self.dir.name)/'images'/entry['image']).read_bytes(), JPEG)

    def test_approve_without_a_point_command_link_is_decision_only(self):
        self.q.sync([cue()])
        rid = self.q.snapshot()[0]['id']
        # No live link at all (or only the arm/disarm bench link): still approvable.
        ok, msg, r = self.q.decide(rid, 'approve', target='quadpi', live=(), action='loiter')
        self.assertTrue(ok)
        self.assertIn('nothing sent', msg)
        self.assertEqual((r['status'], r['decision']['mode'], r['decision']['action']),
                         ('approved', 'decision-only', 'loiter'))
        [entry] = self.entries()
        self.assertEqual((entry['outcome'], entry['mode'], entry['target']),
                         ('approved', 'decision-only', 'quadpi'))

    def test_stale_position_cannot_be_approved(self):
        self.q.sync([cue()])
        rid = self.q.snapshot()[0]['id']
        self.clock.now += APPROVE_MAX_AGE_S + 1
        ok, msg, _ = self.q.decide(rid, 'approve', target='quadpi', live=('quadpi',))
        self.assertFalse(ok)
        self.assertIn('old', msg)

    def test_mission_launch_ignores_position_age(self):
        # Arm & fly mission flies the aircraft's own mission, not the cue's point.
        self.q.sync([cue()])
        rid = self.q.snapshot()[0]['id']
        self.clock.now += APPROVE_MAX_AGE_S + 1
        ok, msg, r = self.q.decide(rid, 'approve', target='rn03', live=('rn03',), action='arm_mission')
        self.assertTrue(ok, msg)
        self.assertEqual((r['decision']['target'], r['decision']['action'], r['decision']['mode']),
                         ('rn03', 'arm_mission', 'live'))
        [entry] = self.entries()
        self.assertEqual((entry['outcome'], entry['target']), ('approved', 'rn03'))

    def test_unknown_command_is_refused(self):
        self.q.sync([cue()])
        rid = self.q.snapshot()[0]['id']
        self.assertFalse(self.q.decide(rid, 'approve', target='quadpi', live=('quadpi',), action='disarm')[0])

    def test_deny_with_reason_suppresses_reoffer_then_drops(self):
        self.q.sync([cue()])
        rid = self.q.snapshot()[0]['id']
        self.assertFalse(self.q.decide(rid, 'deny', reason='made up')[0])
        self.assertTrue(self.q.decide(rid, 'deny', reason='False detection')[0])
        self.clock.now += 30
        self.q.sync([cue()])
        self.assertEqual([r['status'] for r in self.q.snapshot()], ['denied'])
        self.clock.now += KEEP_DECIDED_S + 1
        self.assertEqual(self.q.snapshot(), [])
        self.q.sync([cue()])   # seen again much later: offered afresh
        self.assertEqual([r['status'] for r in self.q.snapshot()], ['pending'])
        self.assertEqual(self.entries()[0]['reason'], 'False detection')

    def test_pending_expires_and_is_logged(self):
        self.q.sync([cue()])
        self.clock.now += PENDING_TTL_S + 1
        self.assertEqual([r['status'] for r in self.q.snapshot()], ['expired'])
        self.assertEqual(self.entries()[0]['outcome'], 'expired')
        self.assertFalse(self.q.decide('H1', 'approve', target='quadpi', live=('quadpi',))[0])

    def test_unknown_request_and_decision(self):
        self.assertFalse(self.q.decide('H99', 'approve')[0])
        self.q.sync([cue()])
        self.assertFalse(self.q.decide('H1', 'launch')[0])


if __name__ == '__main__':
    unittest.main()
