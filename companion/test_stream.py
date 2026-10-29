"""Config and chip-framing checks for stream.py.

No camera and no network: the publisher's socket is replaced, and chip_jpeg
(numpy/simplejpeg, on the Pi only) is never called.
"""
import base64
import json
from pathlib import Path
import tempfile
import unittest

import stream

EXAMPLE = Path(__file__).parent / "config.example.json"


def load(**observe):
    c = json.loads(EXAMPLE.read_text())
    c["android_ip"] = "100.100.0.60"
    c["observe"].update(observe)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "config.json")
        p.write_text(json.dumps(c))
        return stream.load_config(p)


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, _addr):
        self.sent.append(data)


def publisher():
    pub = stream.Publisher(15620)
    pub.sock.close()
    pub.sock = FakeSocket()
    return pub


class Config(unittest.TestCase):
    def test_chips_off_in_the_example_config(self):
        cfg = load()
        self.assertIs(cfg["chips"], False)
        self.assertEqual(cfg["chip_seconds"], 10.0)

    def test_chips_enabled(self):
        self.assertIs(load(chips=True)["chips"], True)

    def test_chips_must_be_a_boolean(self):
        for value in ("yes", 1, None):
            with self.assertRaises(ValueError):
                load(chips=value)

    def test_chip_seconds_bounds(self):
        self.assertEqual(load(chip_seconds=2)["chip_seconds"], 2.0)
        self.assertEqual(load(chip_seconds=600)["chip_seconds"], 600.0)
        for value in (1.9, 601, "10", True, None):
            with self.assertRaises(ValueError):
                load(chip_seconds=value)


class Chips(unittest.TestCase):
    def jpeg(self, size):
        """Stand-in JPEG: only its length matters to the framing."""
        return b"\xff\xd8\xff" + bytes(size - 5) + b"\xff\xd9"

    def test_send_returns_the_seq_a_chip_names(self):
        pub = publisher()
        first = pub.send("person", 0.8, 0.5, 0.5, [0.4, 0.4, 0.2, 0.2], 66.0, 49.0)
        second = pub.send("car", 0.7, 0.5, 0.5, [0.4, 0.4, 0.2, 0.2], 66.0, 49.0)
        self.assertEqual((first, second), (1, 2))
        self.assertEqual(len(pub.sock.sent), 2)

    def test_parts_stay_under_the_tap_cap_and_rebuild_the_jpeg(self):
        pub = publisher()
        jpeg = self.jpeg(3000)
        self.assertTrue(pub.send_chip(93, jpeg))
        parts = [json.loads(d) for d in pub.sock.sent]
        self.assertTrue(all(len(d) <= 512 for d in pub.sock.sent))
        self.assertEqual([p["part"] for p in parts], list(range(len(parts))))
        self.assertEqual({p["parts"] for p in parts}, {len(parts)})
        self.assertEqual({p["chip"] for p in parts}, {93})
        for p in parts:
            self.assertLessEqual(len(p["jpg"]), stream.CHIP_PART_CHARS)
            # Every part decodes on its own: the cut is on a 4-char boundary.
            self.assertEqual(len(p["jpg"]) % 4, 0)
            base64.b64decode(p["jpg"], validate=True)
        self.assertEqual(base64.b64decode("".join(p["jpg"] for p in parts)), jpeg)

    def test_an_oversized_chip_sends_nothing(self):
        pub = publisher()
        self.assertFalse(pub.send_chip(1, self.jpeg(32000)))
        self.assertEqual(pub.sock.sent, [])

    def test_part_size_is_a_base64_boundary(self):
        self.assertEqual(stream.CHIP_PART_CHARS % 4, 0)


if __name__ == "__main__":
    unittest.main()
