# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.notebook (Jupyter-Helfer)."""
import unittest
from datetime import datetime, timedelta

from aion import (
    TypeHierarchy, ClinicalEvent, CausalGraph, SQLiteEventStore, TCFG,
)
from aion.notebook import (
    hierarchy_to_html, events_to_html, sequences_from_store,
)


def _has_matplotlib() -> bool:
    try:
        import matplotlib  # noqa
        return True
    except ImportError:
        return False


class TestHtmlRendering(unittest.TestCase):
    """HTML-Renderer brauchen kein IPython oder matplotlib."""

    def test_empty_hierarchy(self):
        h = TypeHierarchy()
        html = hierarchy_to_html(h)
        # Keine Datenzeilen, aber Tabellen-Skelett
        self.assertIn("<table", html)
        self.assertIn("<thead", html)
        self.assertEqual(html.count("<tr>"), 0)  # Header zählt anders

    def test_hierarchy_with_types(self):
        h = TypeHierarchy()
        h.add_type("Diagnose", attributes={"code": {"type": "string"}},
                   description="Klinische Diagnose")
        h.add_type("Sepsis", parent="Diagnose")

        html = hierarchy_to_html(h)
        self.assertIn("Diagnose", html)
        self.assertIn("Sepsis", html)
        self.assertIn("Klinische Diagnose", html)
        # Zwei Datenzeilen
        self.assertEqual(html.count("<tr>"), 2)

    def test_events_empty(self):
        html = events_to_html([])
        self.assertIn("Keine Ereignisse", html)

    def test_events_with_data(self):
        base = datetime(2026, 5, 1, 10, 0)
        events = [
            ClinicalEvent(
                patient_id="P-001", event_type="Aufnahme",
                t_start=base, t_end=base,
                stay_start=base, stay_end=base + timedelta(days=1),
                attributes={"abteilung": "ICU"},
            ),
            ClinicalEvent(
                patient_id="P-001", event_type="Sepsis",
                t_start=base + timedelta(hours=1),
                t_end=base + timedelta(hours=1),
                stay_start=base, stay_end=base + timedelta(days=1),
                attributes={"sofa": 8, "lactate": 4.2},
            ),
        ]
        html = events_to_html(events)
        self.assertIn("P-001", html)
        self.assertIn("Aufnahme", html)
        self.assertIn("Sepsis", html)
        self.assertIn("2 Ereignisse", html)
        # Attribute werden gekürzt — sofa=8 ist drin
        self.assertIn("sofa=8", html)

    def test_events_truncation(self):
        """Bei vielen Events wird die Tabelle gekürzt."""
        base = datetime(2026, 5, 1, 10, 0)
        events = [
            ClinicalEvent(
                patient_id=f"P-{i:03d}", event_type="Aufnahme",
                t_start=base, t_end=base,
                stay_start=base, stay_end=base + timedelta(days=1),
            )
            for i in range(100)
        ]
        html = events_to_html(events, max_rows=10)
        self.assertIn("100 Ereignisse", html)
        # Suffix mit "…und N weitere"
        self.assertIn("90 weitere", html)


class TestSequencesFromStore(unittest.TestCase):
    """Sequenz-Extraktion aus DB."""

    def test_empty_store(self):
        with SQLiteEventStore(":memory:") as store:
            sequences = sequences_from_store(store)
        self.assertEqual(sequences, [])

    def test_sequences_chronological(self):
        """Events werden chronologisch sortiert pro Patient."""
        base = datetime(2026, 5, 1, 10, 0)
        with SQLiteEventStore(":memory:") as store:
            # Events in zufälliger Reihenfolge einfügen
            for offset, typ in [(2, "Sepsis"), (0, "Aufnahme"), (1, "Fieber")]:
                store.add(ClinicalEvent(
                    patient_id="P-001", event_type=typ,
                    t_start=base + timedelta(hours=offset),
                    t_end=base + timedelta(hours=offset),
                    stay_start=base, stay_end=base + timedelta(days=1),
                ))

            sequences = sequences_from_store(store)

        self.assertEqual(len(sequences), 1)
        # Trotz Insert-Reihenfolge: chronologisch ausgegeben
        self.assertEqual(sequences[0], ["Aufnahme", "Fieber", "Sepsis"])

    def test_sequences_per_patient(self):
        """Jeder Patient bekommt seine eigene Sequenz."""
        base = datetime(2026, 5, 1, 10, 0)
        with SQLiteEventStore(":memory:") as store:
            for pid in ["P-1", "P-2"]:
                for offset, typ in enumerate(["A", "B", "C"]):
                    store.add(ClinicalEvent(
                        patient_id=pid, event_type=typ,
                        t_start=base + timedelta(hours=offset),
                        t_end=base + timedelta(hours=offset),
                        stay_start=base, stay_end=base + timedelta(days=1),
                    ))
            sequences = sequences_from_store(store)

        self.assertEqual(len(sequences), 2)
        self.assertTrue(all(seq == ["A", "B", "C"] for seq in sequences))

    def test_filter_by_patient_ids(self):
        base = datetime(2026, 5, 1, 10, 0)
        with SQLiteEventStore(":memory:") as store:
            for pid in ["P-1", "P-2", "P-3"]:
                store.add(ClinicalEvent(
                    patient_id=pid, event_type="X",
                    t_start=base, t_end=base,
                    stay_start=base, stay_end=base + timedelta(days=1),
                ))

            seqs_filtered = sequences_from_store(store, patient_ids=["P-1", "P-3"])

        self.assertEqual(len(seqs_filtered), 2)


@unittest.skipUnless(_has_matplotlib(), "matplotlib nicht installiert")
class TestPlotting(unittest.TestCase):
    """Plot-Funktionen — nur ausgeführt wenn matplotlib da ist."""

    @classmethod
    def setUpClass(cls):
        import matplotlib
        matplotlib.use("Agg")  # Kein Display

    def test_plot_pattern_support_basic(self):
        from aion.notebook import plot_pattern_support
        patterns = {
            ("A", "B"): 0.8,
            ("B", "C"): 0.6,
            ("A", "B", "C"): 0.5,
        }
        fig = plot_pattern_support(patterns)
        # Figure-Objekt zurückgegeben
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_plot_pattern_support_empty(self):
        from aion.notebook import plot_pattern_support
        fig = plot_pattern_support({})
        # Soll nicht crashen, sondern leere Figure mit Hinweistext
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_plot_causal_graph_basic(self):
        from aion.notebook import plot_causal_graph
        g = CausalGraph()
        g.add_edge("Z", "T"); g.add_edge("Z", "Y"); g.add_edge("T", "Y")
        fig = plot_causal_graph(g, treatment="T", outcome="Y", backdoor_set={"Z"})
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_plot_causal_graph_empty(self):
        from aion.notebook import plot_causal_graph
        fig = plot_causal_graph(CausalGraph())
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)


class TestMatplotlibLazyImport(unittest.TestCase):

    def test_clear_error_when_matplotlib_missing(self):
        """Wenn matplotlib fehlt, soll plot_*-Aufruf einen klaren Fehler liefern."""
        if _has_matplotlib():
            self.skipTest("matplotlib installiert — kann ImportError-Pfad nicht testen")
        from aion.notebook import plot_pattern_support
        with self.assertRaises(ImportError) as ctx:
            plot_pattern_support({("A",): 1.0})
        self.assertIn("pip install", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
