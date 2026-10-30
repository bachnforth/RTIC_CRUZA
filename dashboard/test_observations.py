import unittest
from observations import ObservationStore, validate


def record(cls="person", score=0.8, az=10.0, el=-5.0, bbox=None):
    return {"cls": cls, "score": score, "az_rel_deg": az, "el_rel_deg": el,
            "bbox": bbox if bbox is not None else [0.2, 0.3, 0.1, 0.15]}


class ValidateTests(unittest.TestCase):
    def test_well_formed_record_passes(self):
        self.assertIsNotNone(validate(record()))

    def test_non_finite_fields_are_rejected(self):
        for field in ("score", "az_rel_deg", "el_rel_deg"):
            r = record()
            r[field] = float("nan")
            self.assertIsNone(validate(r), field)
        bad = record(bbox=[0.1, float("inf"), 0.2, 0.3])
        self.assertIsNone(validate(bad))

    def test_out_of_range_values_are_rejected(self):
        self.assertIsNone(validate(record(score=1.5)))
        self.assertIsNone(validate(record(az=120)))
        self.assertIsNone(validate(record(el=-200)))

    def test_bad_class_name_is_rejected(self):
        self.assertIsNone(validate(record(cls="../etc/passwd")))
        self.assertIsNone(validate(record(cls="")))
        self.assertIsNone(validate(record(cls="x" * 41)))

    def test_bbox_shape_is_enforced_and_clamped(self):
        self.assertIsNone(validate(record(bbox=[0.1, 0.2, 0.3])))
        clean = validate(record(bbox=[-0.5, 0.2, 2.0, 0.3]))
        self.assertEqual(clean["bbox"], [0.0, 0.2, 1.0, 0.3])


class StoreTests(unittest.TestCase):
    def test_same_class_and_bearing_merges(self):
        s = ObservationStore()
        self.assertTrue(s.add(record(az=10.0), now=100))
        self.assertTrue(s.add(record(az=11.0, score=0.9), now=101))
        snap = s.snapshot(now=101)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["count"], 2)
        self.assertEqual(snap[0]["score"], 0.9)  # strongest kept

    def test_different_bearing_is_a_separate_area(self):
        s = ObservationStore()
        s.add(record(az=-30.0), now=100)
        s.add(record(az=40.0), now=100)
        self.assertEqual(len(s.snapshot(now=100)), 2)

    def test_entries_expire(self):
        s = ObservationStore(ttl=20)
        s.add(record(), now=100)
        self.assertEqual(len(s.snapshot(now=115)), 1)
        self.assertEqual(len(s.snapshot(now=130)), 0)

    def test_malformed_records_are_not_kept(self):
        s = ObservationStore()
        self.assertFalse(s.add({"cls": "person"}, now=100))
        self.assertFalse(s.add("not a dict", now=100))
        self.assertEqual(len(s.snapshot(now=100)), 0)

    def test_cap_is_enforced(self):
        s = ObservationStore(max_entries=3)
        for i in range(10):
            s.add(record(cls="car", az=float(i * 10 - 45)), now=100 + i)
        self.assertLessEqual(len(s.snapshot(now=110)), 3)

    def test_strongest_most_recent_first(self):
        s = ObservationStore()
        s.add(record(cls="car", az=-30, score=0.6), now=100)
        s.add(record(cls="person", az=30, score=0.95), now=100)
        self.assertEqual(s.snapshot(now=100)[0]["cls"], "person")


if __name__ == "__main__":
    unittest.main()
