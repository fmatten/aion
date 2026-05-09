# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Tests für TypeHierarchy."""
import unittest
from aion.core.types import TypeHierarchy, TypeHierarchyError


class TestTypeHierarchy(unittest.TestCase):

    def setUp(self):
        self.h = TypeHierarchy()

    def test_initial_state(self):
        self.assertEqual(len(self.h), 0)
        self.assertIn(self.h.TOP, self.h)

    def test_add_type(self):
        node = self.h.add_type("Diagnose")
        self.assertEqual(node.name, "Diagnose")
        self.assertEqual(len(self.h), 1)
        self.assertIn("Diagnose", self.h)

    def test_add_subtype(self):
        self.h.add_type("Diagnose")
        self.h.add_type("Herzinfarkt", parent="Diagnose")
        self.assertTrue(self.h.is_subtype("Herzinfarkt", "Diagnose"))
        self.assertTrue(self.h.is_subtype("Herzinfarkt", self.h.TOP))

    def test_duplicate_raises(self):
        self.h.add_type("X")
        with self.assertRaises(TypeHierarchyError):
            self.h.add_type("X")

    def test_unknown_parent_raises(self):
        with self.assertRaises(TypeHierarchyError):
            self.h.add_type("Y", parent="DoesNotExist")

    def test_top_cannot_be_added(self):
        with self.assertRaises(TypeHierarchyError):
            self.h.add_type(self.h.TOP)

    def test_transitive_closure(self):
        self.h.add_type("A")
        self.h.add_type("B", parent="A")
        self.h.add_type("C", parent="B")
        self.assertTrue(self.h.is_subtype("C", "A"))
        self.assertTrue(self.h.is_subtype("C", "B"))
        self.assertFalse(self.h.is_subtype("A", "C"))

    def test_reflexivity(self):
        self.h.add_type("X")
        self.assertTrue(self.h.is_subtype("X", "X"))

    def test_multi_inheritance(self):
        self.h.add_type("A")
        self.h.add_type("B")
        self.h.add_type("C", parent="A")
        self.h.add_edge("C", "B")
        self.assertIn("A", self.h.parents_of("C"))
        self.assertIn("B", self.h.parents_of("C"))

    def test_cycle_prevention(self):
        self.h.add_type("A")
        self.h.add_type("B", parent="A")
        with self.assertRaises(TypeHierarchyError):
            # B → A bestehend; A → B würde Zyklus bilden
            self.h.add_edge("A", "B")

    def test_remove_type_reparents(self):
        self.h.add_type("A")
        self.h.add_type("B", parent="A")
        self.h.add_type("C", parent="B")
        self.h.remove_type("B")
        self.assertNotIn("B", self.h)
        self.assertTrue(self.h.is_subtype("C", self.h.TOP))

    def test_descendants(self):
        self.h.add_type("A")
        self.h.add_type("B", parent="A")
        self.h.add_type("C", parent="B")
        descs = self.h.descendants("A")
        self.assertEqual(descs, frozenset({"B", "C"}))

    def test_depth(self):
        self.h.add_type("A")
        self.h.add_type("B", parent="A")
        self.h.add_type("C", parent="B")
        self.assertEqual(self.h.depth("A"), 1)
        self.assertEqual(self.h.depth("B"), 2)
        self.assertEqual(self.h.depth("C"), 3)

    def test_serialization_roundtrip(self):
        self.h.add_type("A", fhir_resource="Condition")
        self.h.add_type("B", parent="A", attributes={"x": {"type": "int"}})
        d = self.h.to_dict()
        h2 = TypeHierarchy.from_dict(d)
        self.assertEqual(len(h2), 2)
        self.assertTrue(h2.is_subtype("B", "A"))
        self.assertEqual(h2.get("B").attributes, {"x": {"type": "int"}})

    def test_validate_attribute_int_range(self):
        self.h.add_type("Vital", attributes={"hr": {"type": "int", "range": [0, 250]}})
        self.assertTrue(self.h.validate_attribute("Vital", "hr", 80))
        self.assertFalse(self.h.validate_attribute("Vital", "hr", 500))
        self.assertFalse(self.h.validate_attribute("Vital", "hr", "abc"))

    def test_validate_attribute_inherited(self):
        self.h.add_type("Vital", attributes={"hr": {"type": "int"}})
        self.h.add_type("ECG", parent="Vital")
        # hr ist von Vital geerbt
        self.assertTrue(self.h.validate_attribute("ECG", "hr", 80))


if __name__ == "__main__":
    unittest.main()
