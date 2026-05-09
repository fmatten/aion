# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Tests für SQLiteEventStore."""
import unittest
from datetime import datetime, timedelta
from aion.core.events import ClinicalEvent
from aion.persistence.sqlite_store import SQLiteEventStore


def _ev(pid="P001", typ="Diagnose", **overrides) -> ClinicalEvent:
    """Helper zum Erzeugen von Test-Ereignissen."""
    base = datetime(2026, 1, 1, 8, 0, 0)
    return ClinicalEvent(
        patient_id=pid,
        event_type=typ,
        t_start=overrides.get("t_start", base),
        t_end=overrides.get("t_end", base + timedelta(hours=1)),
        stay_start=overrides.get("stay_start", base - timedelta(hours=2)),
        stay_end=overrides.get("stay_end", base + timedelta(days=2)),
        attributes=overrides.get("attributes", {}),
        references=overrides.get("references", {}),
        confidence=overrides.get("confidence", 1.0),
    )


class TestSQLiteEventStore(unittest.TestCase):

    def setUp(self):
        self.store = SQLiteEventStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_initial_empty(self):
        self.assertEqual(self.store.count(), 0)

    def test_add_and_get(self):
        e = _ev()
        self.store.add(e)
        self.assertEqual(self.store.count(), 1)
        loaded = self.store.get(e.event_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.patient_id, "P001")
        self.assertEqual(loaded.event_type, "Diagnose")

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.store.get("nicht-existent"))

    def test_attributes_roundtrip(self):
        e = _ev(attributes={"code": "I21.0", "severity": "moderate"})
        self.store.add(e)
        loaded = self.store.get(e.event_id)
        self.assertEqual(loaded.attributes, {"code": "I21.0", "severity": "moderate"})

    def test_references_persistence(self):
        from aion.core.relations import EventRelation
        e1 = _ev()
        e2 = _ev(typ="Beobachtung",
                 references={e1.event_id: EventRelation.OBSERVATION_OF})
        self.store.add_many([e1, e2])
        loaded = self.store.get(e2.event_id)
        self.assertEqual(loaded.references, {e1.event_id: "observation_of"})
        # Inverse Suche
        referrers = self.store.referenced_by(e1.event_id)
        self.assertIn(e2.event_id, referrers)
        self.assertEqual(referrers[e2.event_id], "observation_of")

    def test_find_by_relation(self):
        from aion.core.relations import EventRelation
        e1 = _ev()
        e2 = _ev(typ="Beobachtung",
                 references={e1.event_id: EventRelation.CONFIRMS})
        e3 = _ev(typ="Medikation",
                 references={e1.event_id: EventRelation.RESPONSE_TO})
        self.store.add_many([e1, e2, e3])
        confirms_pairs = self.store.find_by_relation("confirms")
        self.assertEqual(len(confirms_pairs), 1)
        self.assertEqual(confirms_pairs[0], (e2.event_id, e1.event_id))

    def test_find_by_patient(self):
        self.store.add_many([_ev(pid="P001"), _ev(pid="P002"), _ev(pid="P001")])
        events_p1 = self.store.find_by_patient("P001")
        self.assertEqual(len(events_p1), 2)

    def test_find_by_type(self):
        self.store.add_many([
            _ev(typ="Diagnose"),
            _ev(typ="Beobachtung"),
            _ev(typ="Diagnose"),
        ])
        diags = self.store.find_by_type("Diagnose")
        self.assertEqual(len(diags), 2)

    def test_find_in_window(self):
        base = datetime(2026, 1, 1, 12, 0)
        early = _ev(t_start=base - timedelta(hours=10), t_end=base - timedelta(hours=9))
        mid   = _ev(t_start=base - timedelta(hours=1), t_end=base + timedelta(hours=1))
        late  = _ev(t_start=base + timedelta(hours=10), t_end=base + timedelta(hours=11))
        self.store.add_many([early, mid, late])
        result = self.store.find_in_window(
            "P001",
            base - timedelta(hours=2),
            base + timedelta(hours=2),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event_id, mid.event_id)

    def test_find_by_attribute(self):
        e1 = _ev(attributes={"code": "I21.0"})
        e2 = _ev(attributes={"code": "J18.9"})
        self.store.add_many([e1, e2])
        result = self.store.find_by_attribute("code", "I21.0")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event_id, e1.event_id)

    def test_update(self):
        e = _ev(attributes={"x": 1})
        self.store.add(e)
        e.attributes["x"] = 99
        ok = self.store.update(e)
        self.assertTrue(ok)
        loaded = self.store.get(e.event_id)
        self.assertEqual(loaded.attributes["x"], 99)

    def test_delete(self):
        e = _ev()
        self.store.add(e)
        self.assertTrue(self.store.delete(e.event_id))
        self.assertIsNone(self.store.get(e.event_id))
        self.assertFalse(self.store.delete(e.event_id))  # erneut → False

    def test_delete_cascades_references(self):
        e1 = _ev()
        e2 = _ev(typ="Beobachtung", references={e1.event_id: "references"})
        self.store.add_many([e1, e2])
        self.store.delete(e2.event_id)
        # Refs für e2 müssen weg sein
        self.assertEqual(self.store.referenced_by(e1.event_id), {})

    def test_patient_summary(self):
        self.store.add_many([
            _ev(pid="P001", typ="Diagnose"),
            _ev(pid="P001", typ="Diagnose"),
            _ev(pid="P001", typ="Beobachtung"),
        ])
        s = self.store.patient_summary("P001")
        self.assertEqual(s["event_count"], 3)
        self.assertEqual(s["by_type"]["Diagnose"], 2)
        self.assertEqual(s["by_type"]["Beobachtung"], 1)

    def test_context_manager(self):
        with SQLiteEventStore(":memory:") as s:
            s.add(_ev())
            self.assertEqual(s.count(), 1)


if __name__ == "__main__":
    unittest.main()
