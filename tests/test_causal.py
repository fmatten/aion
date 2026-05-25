# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Tests für CausalGraph."""
import unittest
from aion.core.causal import CausalGraph, CausalGraphError


class TestCausalGraph(unittest.TestCase):

    def test_add_node_idempotent(self):
        g = CausalGraph()
        g.add_node("X")
        g.add_node("X")
        self.assertEqual(len(g.nodes()), 1)

    def test_add_edge_creates_nodes(self):
        g = CausalGraph()
        g.add_edge("A", "B")
        self.assertIn("A", g.nodes())
        self.assertIn("B", g.nodes())
        self.assertEqual(g.edges(), [("A", "B")])

    def test_self_loop_rejected(self):
        g = CausalGraph()
        g.add_node("A")
        with self.assertRaises(CausalGraphError):
            g.add_edge("A", "A")

    def test_cycle_prevention(self):
        g = CausalGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        with self.assertRaises(CausalGraphError):
            g.add_edge("C", "A")  # würde Zyklus erzeugen

    def test_topological_order(self):
        g = CausalGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("A", "C")
        order = g.topological_order()
        self.assertEqual(order.index("A"), 0)
        self.assertLess(order.index("A"), order.index("B"))
        self.assertLess(order.index("B"), order.index("C"))

    def test_ancestors_descendants(self):
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("X", "Y")
        g.add_edge("Z", "Y")
        self.assertEqual(g.ancestors("Y"), {"X", "Z"})
        self.assertEqual(g.descendants("Z"), {"X", "Y"})

    def test_backdoor_set_classic_confounder(self):
        """Z → X, Z → Y, X → Y. Backdoor-Set: {Z}."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        g.add_edge("X", "Y")
        bs = g.find_backdoor_adjustment_set("X", "Y")
        self.assertEqual(bs, {"Z"})

    def test_backdoor_set_excludes_descendants(self):
        """Mediator M zwischen X und Y darf nicht im Adjustment-Set sein."""
        g = CausalGraph()
        g.add_edge("Z", "X")
        g.add_edge("Z", "Y")
        g.add_edge("X", "M")
        g.add_edge("M", "Y")
        bs = g.find_backdoor_adjustment_set("X", "Y")
        self.assertNotIn("M", bs)
        self.assertIn("Z", bs)

    def test_backdoor_paths_count(self):
        g = CausalGraph()
        g.add_edge("Z1", "X")
        g.add_edge("Z1", "Y")
        g.add_edge("Z2", "X")
        g.add_edge("Z2", "Y")
        g.add_edge("X", "Y")
        # Es gibt mindestens zwei Backdoor-Pfade X ← Z1 → Y und X ← Z2 → Y
        paths = g.backdoor_paths("X", "Y")
        self.assertGreaterEqual(len(paths), 2)

    def test_remove_node_cleans_edges(self):
        g = CausalGraph()
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.remove_node("B")
        self.assertNotIn("B", g.nodes())
        self.assertEqual(g.edges(), [])

    def test_serialization_roundtrip(self):
        g = CausalGraph()
        g.add_edge("X", "Y")
        g.add_edge("Z", "Y")
        d = g.to_dict()
        g2 = CausalGraph.from_dict(d)
        self.assertEqual(set(g2.nodes()), {"X", "Y", "Z"})
        self.assertEqual(set(g2.edges()), {("X", "Y"), ("Z", "Y")})

    def test_dot_format_smoke(self):
        g = CausalGraph()
        g.add_edge("X", "Y")
        dot = g.to_dot()
        self.assertIn("digraph", dot)
        self.assertIn("\"X\" -> \"Y\"", dot)

    def test_do_backdoor_with_empty_z(self):
        """Wenn keine Confounder existieren, P(Y|do(X)) = P(Y|X)."""
        g = CausalGraph()
        g.add_edge("X", "Y")

        def p_y_x(x, y, z):
            return 0.7 if (x == "1" and y == "1") else 0.3

        def p_z(z):
            return 1.0

        result = g.do_backdoor(p_y_x, p_z, {}, "X", "Y", "1", "1")
        self.assertAlmostEqual(result, 0.7)


if __name__ == "__main__":
    unittest.main()
