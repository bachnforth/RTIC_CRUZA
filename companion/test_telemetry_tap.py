"""Frame parsing and per-sender thinning key for telemetry-tap.py.

The tap runs on the Pi: it imports `pwd` to drop privileges before capturing.
Nothing here calls main(), so on a non-Linux laptop `pwd` is stubbed for the
import alone; no socket is opened and no privilege is dropped.
"""
import importlib.util
from pathlib import Path
import sys
import types
import unittest


def load_tap():
    stubbed = "pwd" not in sys.modules and not _has_pwd()
    if stubbed:
        sys.modules["pwd"] = types.ModuleType("pwd")
    try:
        spec = importlib.util.spec_from_file_location(
            "telemetry_tap", Path(__file__).parent / "telemetry-tap.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if stubbed:
            del sys.modules["pwd"]


def _has_pwd():
    try:
        import pwd  # noqa: F401
    except ImportError:
        return False
    return True


def v2(msgid, sysid, compid, payload=b"\x00" * 9):
    """A MAVLink 2 frame: magic, len, incompat, compat, seq, sysid, compid, id."""
    return (bytes([253, len(payload), 0, 0, 0, sysid, compid])
            + msgid.to_bytes(3, "little") + payload + b"\x00\x00")


def v1(msgid, sysid, compid, payload=b"\x00" * 9):
    """A MAVLink 1 frame: magic, len, seq, sysid, compid, id."""
    return bytes([254, len(payload), 0, sysid, compid, msgid]) + payload + b"\x00\x00"


class Sender(unittest.TestCase):
    def setUp(self):
        self.tap = load_tap()

    def test_sysid_and_compid_come_from_the_right_offsets(self):
        self.assertEqual(self.tap.sender(v2(0, 1, 1)), bytes([1, 1]))
        self.assertEqual(self.tap.sender(v1(0, 1, 1)), bytes([1, 1]))
        # A phone GCS: same message id, different sender.
        self.assertEqual(self.tap.sender(v2(0, 255, 190)), bytes([255, 190]))
        self.assertEqual(self.tap.sender(v1(0, 255, 190)), bytes([255, 190]))

    def test_the_autopilot_heartbeat_is_not_thinned_by_a_gcs_heartbeat(self):
        """The bug on 28 Oct: thinning keyed on the message id alone meant the
        phone's 1 Hz HEARTBEAT, arriving first, dropped the autopilot's."""
        autopilot, gcs = v2(0, 1, 1), v2(0, 255, 190)
        last, now = {}, 100.0
        kept = []
        for raw in (gcs, autopilot, gcs, autopilot):
            key = (0, self.tap.sender(raw))
            if now - last.get(key, -100) >= .5:
                kept.append(raw)
                last[key] = now
        self.assertEqual(kept, [gcs, autopilot])  # one of each, neither crowded out

    def test_frames_are_split_and_filtered_by_id(self):
        heartbeat, unwanted = v2(0, 1, 1), v2(999, 1, 1)
        found = list(self.tap.mav_frames(heartbeat + unwanted + heartbeat))
        self.assertEqual([mid for mid, _ in found], [0, 0])
        self.assertEqual([raw for _, raw in found], [heartbeat, heartbeat])


if __name__ == "__main__":
    unittest.main()
