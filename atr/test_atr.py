import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np
import atr


def detector():
    session = Mock()
    session.get_inputs.return_value = [Mock()]
    with patch('atr.ort.InferenceSession', return_value=session):
        return atr.Detector(Path('unused.onnx'), 416)


def row(out, stride, x, y, size, scores):
    offset = sum((416//s)**2 for s in (8, 16, 32) if s < stride)
    i = offset+y*(416//stride)+x
    out[0, i, :4] = .5, .5, np.log(size/stride), np.log(size/stride)
    out[0, i, 4] = 1
    for cls, score in scores.items():
        out[0, i, 5+cls] = score


class Tests(unittest.TestCase):
    def test_decode_keeps_people_and_vehicles_in_frame_pixels(self):
        d = detector()
        out = np.zeros((1, 3549, 85), np.float32)
        row(out, 8, 10, 5, 32, {0: .9})               # person centred at (84, 44), 32 px
        row(out, 16, 20, 20, 64, {2: .8})             # car centred at (328, 328)
        row(out, 16, 20, 20, 64, {7: .3})             # weak duplicate, below threshold
        row(out, 16, 21, 20, 64, {7: .7})             # truck on the same vehicle
        row(out, 32, 5, 5, 96, {9: .99})              # traffic light: ignored class
        found = d.decode(out, .5, (1000, 1000, 3))
        self.assertEqual(sorted(f['label'] for f in found), ['car', 'person'])
        person = next(f for f in found if f['category'] == 'person')
        self.assertEqual(person['box'], (136, 56, 200, 120))
        self.assertAlmostEqual(person['score'], .9, places=5)

    def test_decode_clips_to_frame_and_handles_empty_output(self):
        d = detector()
        out = np.zeros((1, 3549, 85), np.float32)
        self.assertEqual(d.decode(out, 1, (480, 640, 3)), [])
        row(out, 8, 0, 0, 64, {0: .9})
        self.assertEqual(d.decode(out, 1, (480, 640, 3))[0]['box'], (0, 0, 36, 36))

    def test_letterbox_matches_model_input(self):
        blob, scale = detector().letterbox(np.zeros((480, 640, 3), np.uint8))
        self.assertEqual(blob.shape, (1, 3, 416, 416))
        self.assertAlmostEqual(scale, 416/640)
        self.assertEqual(blob[0, 0, -1, 0], 114)  # Padding below the picture.

    def test_tracker_needs_consecutive_sightings_and_keeps_ids(self):
        t = atr.Tracker(min_hits=3, max_age=1)
        person = dict(category='person', label='person', score=.8, box=(10, 10, 50, 90))
        moved = dict(person, box=(14, 12, 54, 92))
        self.assertEqual(t.update([person], 0), ([], []))
        self.assertEqual(t.update([], .1), ([], []))   # Miss resets an unconfirmed track.
        t.update([person], .2)
        t.update([moved], .3)
        self.assertEqual(t.update([], .35), ([], []))
        t.update([person], .4)
        t.update([moved], .5)
        started, _ = t.update([person], .6)
        self.assertEqual(len(started), 1)
        self.assertEqual([x['id'] for x in t.visible(.6)], [started[0]['id']])
        self.assertEqual(t.update([moved], .7), ([], []))
        _, ended = t.update([], 2)
        self.assertEqual([x['id'] for x in ended], [started[0]['id']])
        self.assertEqual(t.tracks, [])

    def test_tracker_never_matches_person_to_vehicle(self):
        t = atr.Tracker(min_hits=1)
        box = (0, 0, 40, 40)
        t.update([dict(category='person', label='person', score=.9, box=box)], 0)
        started, _ = t.update([dict(category='vehicle', label='car', score=.9, box=box)], .1)
        self.assertEqual([(x['id'], x['label']) for x in started], [(2, 'car')])

    def test_source_names(self):
        self.assertEqual(atr.parse_source('cruza=rtsp://127.0.0.1:8554/cruza'),
                         ('cruza', 'rtsp://127.0.0.1:8554/cruza'))
        for bad in ('rtsp://x', '=x', 'a b=x', 'cruza='):
            with self.assertRaises(argparse.ArgumentTypeError):
                atr.parse_source(bad)

    def test_model_download_rejected_on_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            fake = lambda url, path: Path(path).write_bytes(b'not a model')
            with patch('atr.urllib.request.urlretrieve', side_effect=fake), \
                 patch('builtins.print'), self.assertRaises(RuntimeError):
                atr.fetch_model('yolox_nano', Path(td))
            self.assertEqual(list(Path(td).iterdir()), [])
            body = b'pretend model'
            with patch.dict(atr.MODELS, yolox_nano=(416, hashlib.sha256(body).hexdigest())), \
                 patch('atr.urllib.request.urlretrieve', side_effect=lambda u, p: Path(p).write_bytes(body)), \
                 patch('builtins.print'):
                self.assertEqual(atr.fetch_model('yolox_nano', Path(td)), (Path(td)/'yolox_nano.onnx', 416))


if __name__ == '__main__':
    unittest.main()
