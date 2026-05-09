# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Tests für aion.dowhy-Bridge.

Tests laufen nur, wenn DoWhy installiert ist — sonst werden sie
übersprungen (analog Z3-Tests).
"""
import unittest
import warnings

from aion import CausalGraph, has_dowhy
from aion.dowhy import causal_graph_to_gml


class TestGmlConversion(unittest.TestCase):
    """GML-Export braucht kein DoWhy — läuft immer."""

    def test_simple_graph(self):
        g = CausalGraph()
        g.add_edge("A", "B")
        gml = causal_graph_to_gml(g)
        self.assertIn("graph [", gml)
        self.assertIn("directed 1", gml)
        self.assertIn('label "A"', gml)
        self.assertIn('label "B"', gml)

    def test_three_node_chain(self):
        g = CausalGraph()
        g.add_edge("A", "B"); g.add_edge("B", "C")
        gml = causal_graph_to_gml(g)
        # Drei Knoten, zwei Kanten
        self.assertEqual(gml.count("node ["), 3)
        self.assertEqual(gml.count("edge ["), 2)

    def test_disconnected_nodes(self):
        g = CausalGraph()
        g.add_node("A")
        g.add_node("B")
        # Kein Edge — beide Knoten müssen trotzdem in GML
        gml = causal_graph_to_gml(g)
        self.assertEqual(gml.count("node ["), 2)
        self.assertEqual(gml.count("edge ["), 0)


@unittest.skipUnless(has_dowhy(), "dowhy nicht installiert")
class TestDoWhyIntegration(unittest.TestCase):
    """End-to-End-Tests für die Bridge."""

    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore")  # DoWhy ist warning-laut
        import numpy as np, pandas as pd

        # Klassisches Confounding-Setup, n groß genug für stabile Schätzung
        rng = np.random.default_rng(42)
        n = 2000
        Z = rng.binomial(1, 0.5, n)
        T = rng.binomial(1, 0.3 + 0.4 * Z, n)
        Y = 0.5 * T + 0.6 * Z + rng.normal(0, 0.3, n)

        cls.df = pd.DataFrame({"Z": Z, "T": T, "Y": Y})
        cls.true_ate = 0.5

        cls.graph = CausalGraph()
        cls.graph.add_edge("Z", "T")
        cls.graph.add_edge("Z", "Y")
        cls.graph.add_edge("T", "Y")

    def test_to_dowhy_model_basic(self):
        from aion.dowhy import to_dowhy_model
        model = to_dowhy_model(self.graph, self.df, "T", "Y")
        # DoWhy CausalModel-Klasse
        self.assertEqual(type(model).__name__, "CausalModel")

    def test_treatment_must_be_in_graph(self):
        from aion.dowhy import to_dowhy_model
        with self.assertRaises(ValueError):
            to_dowhy_model(self.graph, self.df, treatment="Unbekannt", outcome="Y")

    def test_outcome_must_be_in_graph(self):
        from aion.dowhy import to_dowhy_model
        with self.assertRaises(ValueError):
            to_dowhy_model(self.graph, self.df, treatment="T", outcome="Unbekannt")

    def test_data_must_have_all_columns(self):
        from aion.dowhy import to_dowhy_model
        df_missing = self.df[["T", "Y"]]  # Z fehlt
        with self.assertRaises(ValueError):
            to_dowhy_model(self.graph, df_missing, "T", "Y")

    def test_estimate_close_to_true_ate(self):
        """Linear-Regression-Schätzung sollte dem wahren ATE nahe sein."""
        from aion.dowhy import to_dowhy_model, estimate_ate
        model = to_dowhy_model(self.graph, self.df, "T", "Y")
        estimate = estimate_ate(model, "backdoor.linear_regression")
        # ATE = 0.5 wahr, Schätzung sollte innerhalb 0.1 sein
        self.assertAlmostEqual(estimate.value, self.true_ate, delta=0.1)

    def test_random_common_cause_robustness(self):
        """Zufällige Common-Causes dürfen Schätzung kaum verändern."""
        from aion.dowhy import to_dowhy_model, refute_estimate
        model = to_dowhy_model(self.graph, self.df, "T", "Y")
        identified = model.identify_effect(proceed_when_unidentifiable=True)
        estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")
        ref = refute_estimate(model, identified, estimate, "random_common_cause")
        # Robust = neue Schätzung nahe der alten (innerhalb 10%)
        self.assertAlmostEqual(ref.new_effect, ref.estimated_effect, delta=0.1)

    def test_placebo_refuter_drops_to_zero(self):
        """Placebo-Treatment muss zu ATE ≈ 0 führen."""
        from aion.dowhy import to_dowhy_model, refute_estimate
        model = to_dowhy_model(self.graph, self.df, "T", "Y")
        identified = model.identify_effect(proceed_when_unidentifiable=True)
        estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")
        ref = refute_estimate(model, identified, estimate, "placebo_treatment_refuter")
        # Mit zufälligem Treatment sollte der Effekt nahe 0 sein
        self.assertLess(abs(ref.new_effect), 0.1)


class TestLazyImport(unittest.TestCase):
    """has_dowhy() liefert einen Bool, ohne dowhy zu importieren falls fehlt."""

    def test_has_dowhy_returns_bool(self):
        result = has_dowhy()
        self.assertIsInstance(result, bool)

    def test_lazy_import_error_message_when_dowhy_missing(self):
        """Wenn dowhy nicht installiert, muss to_dowhy_model() klar fehlschlagen."""
        if has_dowhy():
            self.skipTest("dowhy installiert — kann ImportError-Pfad nicht testen")
        from aion.dowhy import to_dowhy_model
        with self.assertRaises(ImportError) as ctx:
            to_dowhy_model(CausalGraph(), None, "T", "Y")
        # Fehlermeldung muss Installations-Hinweis enthalten
        self.assertIn("pip install", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
