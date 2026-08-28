# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für das aion.verify Modul (Hierarchy + Causal + Z3)."""
import unittest

from aion.core.types import TypeHierarchy
from aion.core.causal import CausalGraph
from aion.verify.hierarchy import (
    check_inheritance_conflicts, check_required_attributes,
    inherited_attributes,
)
from aion.verify.causal import (
    d_separates, is_valid_backdoor_set,
)


class TestHierarchyVerification(unittest.TestCase):

    def test_simple_inheritance_no_conflict(self):
        h = TypeHierarchy()
        h.add_type("Beobachtung", attributes={
            "value": {"type": "float", "range": [0, 100]},
        })
        h.add_type("Vital", parent="Beobachtung")
        report = check_inheritance_conflicts(h)
        self.assertTrue(report.ok, report.summary())

    def test_disjoint_ranges_detected(self):
        """Multi-Inheritance mit disjunkten Ranges → Konflikt."""
        h = TypeHierarchy()
        h.add_type("RangeA", attributes={
            "x": {"type": "int", "range": [0, 10]},
        })
        h.add_type("RangeB", attributes={
            "x": {"type": "int", "range": [20, 30]},
        })
        h.add_type("Combined", parent="RangeA")
        h.add_edge("Combined", "RangeB")  # Multi-Inheritance

        report = check_inheritance_conflicts(h)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.conflicts), 1)
        self.assertIn("Disjunkte", report.conflicts[0].reason)

    def test_type_mismatch_detected(self):
        h = TypeHierarchy()
        h.add_type("A", attributes={"x": {"type": "int"}})
        h.add_type("B", attributes={"x": {"type": "float"}})
        h.add_type("C", parent="A")
        h.add_edge("C", "B")
        report = check_inheritance_conflicts(h)
        self.assertFalse(report.ok)
        self.assertIn("type-Felder", report.conflicts[0].reason)

    def test_enum_specialization_violated(self):
        """Subtyp führt Enum-Wert ein, den Eltern nicht kennt."""
        h = TypeHierarchy()
        h.add_type("Schwere", attributes={
            "level": {"type": "enum", "values": ["mild", "schwer"]},
        })
        h.add_type("ICUSchwere", parent="Schwere", attributes={
            "level": {"type": "enum", "values": ["mild", "schwer", "kritisch"]},
        })
        report = check_inheritance_conflicts(h)
        self.assertFalse(report.ok)
        self.assertIn("kritisch", report.conflicts[0].reason)

    def test_required_attributes_inherited(self):
        h = TypeHierarchy()
        h.add_type("Diagnose", attributes={
            "code": {"type": "string", "required": True},
        })
        h.add_type("Sepsis", parent="Diagnose", attributes={
            "sofa": {"type": "int", "required": True},
        })
        req = check_required_attributes(h, "Sepsis")
        self.assertEqual(req, {"code", "sofa"})

    def test_inherited_attributes_collects_all(self):
        h = TypeHierarchy()
        h.add_type("A", attributes={"x": {"type": "int"}})
        h.add_type("B", parent="A", attributes={"y": {"type": "string"}})
        h.add_type("C", parent="B", attributes={"z": {"type": "bool"}})
        attrs = inherited_attributes(h, "C")
        self.assertEqual(set(attrs.keys()), {"x", "y", "z"})


class TestDSeparation(unittest.TestCase):

    def test_chain_blocked_by_middle(self):
        """X → Z → Y. Z d-trennt X und Y."""
        g = CausalGraph()
        g.add_edge("X", "Z")
        g.add_edge("Z", "Y")
        self.assertTrue(d_separates(g, {"X"}, {"Y"}, {"Z"}))
        self.assertFalse(d_separates(g, {"X"}, {"Y"}, set()))

    def test_fork_blocked_by_common_cause(self):
        """X ← Z → Y. Z d-trennt X und Y."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        self.assertTrue(d_separates(g, {"X"}, {"Y"}, {"Z"}))
        self.assertFalse(d_separates(g, {"X"}, {"Y"}, set()))

    def test_collider_unblocked_when_conditioned(self):
        """X → Z ← Y. Konditionieren auf Collider Z öffnet den Pfad."""
        g = CausalGraph()
        g.add_edge("X", "Z")
        g.add_edge("Y", "Z")
        # Ohne Konditionierung: blockiert (collider)
        self.assertTrue(d_separates(g, {"X"}, {"Y"}, set()))
        # Mit Konditionierung auf Z: NICHT blockiert
        self.assertFalse(d_separates(g, {"X"}, {"Y"}, {"Z"}))


class TestBackdoorValidation(unittest.TestCase):

    def test_valid_backdoor_classic_confounder(self):
        """Z → X, Z → Y, X → Y. Z = {Z} ist gültig."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        g.add_edge("X", "Y")
        report = is_valid_backdoor_set(g, "X", "Y", {"Z"})
        self.assertTrue(report.valid, str(report))

    def test_empty_set_invalid_with_confounder(self):
        """Ohne Konditionierung kein Backdoor blockiert."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        g.add_edge("X", "Y")
        report = is_valid_backdoor_set(g, "X", "Y", set())
        self.assertFalse(report.valid)

    def test_descendant_in_z_invalid(self):
        """Z darf keinen Nachfahren von X enthalten."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        g.add_edge("X", "M")  # Mediator
        g.add_edge("M", "Y")
        # M ist Nachfahre von X, gehört NICHT in Z
        report = is_valid_backdoor_set(g, "X", "Y", {"Z", "M"})
        self.assertFalse(report.valid)
        self.assertTrue(any("Nachfahren" in v for v in report.violations))

    def test_unknown_treatment(self):
        g = CausalGraph()
        g.add_edge("X", "Y")
        report = is_valid_backdoor_set(g, "DOES_NOT_EXIST", "Y", set())
        self.assertFalse(report.valid)


class TestZ3PluginAvailability(unittest.TestCase):
    """Z3 ist optional — wir testen, ob der Plugin-Loader sich sauber verhält."""

    def test_has_z3_returns_bool(self):
        from aion.verify import has_z3
        self.assertIsInstance(has_z3(), bool)

    def test_z3_plugin_imports_or_raises_clearly(self):
        from aion.verify import has_z3
        if has_z3():
            from aion.verify.z3_plugin import check_schema_satisfiability  # noqa
        else:
            # Wenn Z3 nicht da ist, MUSS _require_z3() eine sprechende
            # ImportError werfen, nicht etwas Verwirrendes.
            from aion.verify.z3_plugin import _require_z3
            with self.assertRaises(ImportError) as ctx:
                _require_z3()
            self.assertIn("z3-solver", str(ctx.exception))


@unittest.skipUnless(
    __import__("aion.verify").verify.has_z3(),
    "z3-solver nicht installiert",
)
class TestZ3SchemaSatisfiability(unittest.TestCase):

    def test_simple_satisfiable_schema(self):
        from aion.verify.z3_plugin import check_schema_satisfiability
        h = TypeHierarchy()
        h.add_type("Vital", attributes={
            "hr": {"type": "int", "range": [0, 250]},
        })
        report = check_schema_satisfiability(h, "Vital")
        self.assertTrue(report.satisfiable, str(report))
        self.assertIn("hr", report.model)
        self.assertGreaterEqual(report.model["hr"], 0)
        self.assertLessEqual(report.model["hr"], 250)

    def test_unsatisfiable_disjoint_ranges(self):
        from aion.verify.z3_plugin import check_schema_satisfiability
        h = TypeHierarchy()
        h.add_type("Wide",   attributes={"x": {"type": "int", "range": [0, 10]}})
        h.add_type("Narrow", attributes={"x": {"type": "int", "range": [20, 30]}})
        h.add_type("Combo", parent="Wide")
        h.add_edge("Combo", "Narrow")
        report = check_schema_satisfiability(h, "Combo")
        self.assertFalse(report.satisfiable, str(report))


if __name__ == "__main__":
    unittest.main()
