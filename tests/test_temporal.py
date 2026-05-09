# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Tests für Allen-Algebra."""
import unittest
from aion.core.temporal import AllenInterval, FuzzyAllenInterval, ALL_RELATIONS


class TestAllenInterval(unittest.TestCase):

    def test_before(self):
        self.assertTrue(AllenInterval(1, 3).before(AllenInterval(4, 6)))
        self.assertFalse(AllenInterval(1, 4).before(AllenInterval(3, 5)))

    def test_meets(self):
        self.assertTrue(AllenInterval(1, 3).meets(AllenInterval(3, 5)))
        self.assertFalse(AllenInterval(1, 2).meets(AllenInterval(3, 5)))

    def test_overlaps(self):
        self.assertTrue(AllenInterval(1, 4).overlaps(AllenInterval(3, 6)))
        self.assertFalse(AllenInterval(1, 3).overlaps(AllenInterval(3, 5)))  # = meets

    def test_starts(self):
        self.assertTrue(AllenInterval(1, 3).starts(AllenInterval(1, 5)))
        self.assertFalse(AllenInterval(1, 3).starts(AllenInterval(2, 5)))

    def test_during(self):
        self.assertTrue(AllenInterval(2, 4).during(AllenInterval(1, 5)))
        self.assertFalse(AllenInterval(1, 4).during(AllenInterval(1, 5)))  # = starts

    def test_finishes(self):
        self.assertTrue(AllenInterval(3, 5).finishes(AllenInterval(1, 5)))

    def test_equals(self):
        self.assertTrue(AllenInterval(1, 3).equals(AllenInterval(1, 3)))
        self.assertFalse(AllenInterval(1, 3).equals(AllenInterval(1, 4)))

    def test_contains(self):
        self.assertTrue(AllenInterval(1, 5).contains(AllenInterval(2, 4)))

    def test_after(self):
        self.assertTrue(AllenInterval(5, 7).after(AllenInterval(1, 3)))

    def test_relation_to_uniqueness(self):
        """Die 13 Allen-Relationen sind disjunkt und erschöpfend."""
        cases = [
            (AllenInterval(1, 3), AllenInterval(4, 6), "before"),
            (AllenInterval(1, 3), AllenInterval(3, 5), "meets"),
            (AllenInterval(1, 4), AllenInterval(3, 6), "overlaps"),
            (AllenInterval(1, 3), AllenInterval(1, 5), "starts"),
            (AllenInterval(2, 4), AllenInterval(1, 5), "during"),
            (AllenInterval(3, 5), AllenInterval(1, 5), "finishes"),
            (AllenInterval(1, 3), AllenInterval(1, 3), "equals"),
            (AllenInterval(1, 5), AllenInterval(2, 5), "finished_by"),
            (AllenInterval(1, 5), AllenInterval(2, 4), "contains"),
            (AllenInterval(1, 5), AllenInterval(1, 3), "started_by"),
            (AllenInterval(3, 6), AllenInterval(1, 4), "overlapped_by"),
            (AllenInterval(3, 5), AllenInterval(1, 3), "met_by"),
            (AllenInterval(4, 6), AllenInterval(1, 3), "after"),
        ]
        for i1, i2, expected in cases:
            with self.subTest(i1=i1, i2=i2, expected=expected):
                self.assertEqual(i1.relation_to(i2), expected)
                # Genau eine Relation muss True sein
                trues = [r for r in ALL_RELATIONS if getattr(i1, r)(i2)]
                self.assertEqual(len(trues), 1, f"Mehrdeutigkeit: {trues}")

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            AllenInterval(5, 3)


class TestFuzzy(unittest.TestCase):

    def test_no_uncertainty_yields_exact(self):
        f1 = FuzzyAllenInterval(1, 3, 0, 0)
        f2 = FuzzyAllenInterval(4, 6, 0, 0)
        p = f1.confidence(f2, "before", n_samples=100, seed=42)
        self.assertEqual(p, 1.0)

    def test_distribution_sums_to_one(self):
        f1 = FuzzyAllenInterval(1, 3, 0.5, 0.5)
        f2 = FuzzyAllenInterval(4, 6, 0.5, 0.5)
        d = f1.confidence_distribution(f2, n_samples=1000, seed=42)
        self.assertAlmostEqual(sum(d.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
