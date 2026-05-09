# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Tests für aion.fhir — Round-Trip-Mapper und Bundle-Operations."""
import unittest
from datetime import datetime, timezone, timedelta

try:
    import fhir.resources  # noqa: F401
    HAS_FHIR = True
except ImportError:
    HAS_FHIR = False

from aion.core.events import ClinicalEvent
from aion.core.relations import EventRelation


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def _ev(typ, **overrides) -> ClinicalEvent:
    """Helper-Factory für Test-Events."""
    base = _utc(2026, 3, 1, 10)
    return ClinicalEvent(
        patient_id=overrides.get("patient_id", "P-42"),
        event_type=typ,
        t_start=overrides.get("t_start", base),
        t_end=overrides.get("t_end", base + timedelta(minutes=30)),
        stay_start=overrides.get("stay_start", _utc(2026, 3, 1, 8)),
        stay_end=overrides.get("stay_end", _utc(2026, 3, 5, 12)),
        attributes=overrides.get("attributes", {}),
        references=overrides.get("references", {}),
        confidence=overrides.get("confidence", 1.0),
        event_id=overrides.get("event_id", None) or ClinicalEvent(
            patient_id="x", event_type="x",
            t_start=base, t_end=base, stay_start=base, stay_end=base,
        ).event_id,
    )


def _assert_equivalent(test: unittest.TestCase, e1: ClinicalEvent, e2: ClinicalEvent):
    """Gemeinsame Round-Trip-Assertions, die bei jedem Mapping gelten müssen."""
    test.assertEqual(e1.patient_id, e2.patient_id, "patient_id mismatch")
    test.assertEqual(e1.event_type, e2.event_type, "event_type mismatch")
    test.assertEqual(e1.t_start, e2.t_start, "t_start mismatch")
    test.assertEqual(e1.references, e2.references, "references mismatch")
    test.assertEqual(e1.confidence, e2.confidence, "confidence mismatch")


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestObservationRoundTrip(unittest.TestCase):

    def test_simple_observation(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Laktatmessung", attributes={"value": 4.2, "unit": "mmol/L"})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        _assert_equivalent(self, e, e2)
        self.assertAlmostEqual(e.attributes["value"], e2.attributes["value"])
        self.assertEqual(e.attributes["unit"], e2.attributes["unit"])

    def test_observation_with_components(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Blutdruckmessung", attributes={"systolic": 130, "diastolic": 85})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        _assert_equivalent(self, e, e2)
        self.assertEqual(int(e2.attributes["systolic"]), 130)
        self.assertEqual(int(e2.attributes["diastolic"]), 85)

    def test_observation_with_extension_attributes(self):
        """Nicht-numerische Attribute landen in AION_ATTRIBUTE_URL-Extensions."""
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Befund", attributes={"value": 4.2, "unit": "mmol/L",
                                      "method": "blood_gas", "lab_id": "ABC123"})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        self.assertEqual(e.attributes, e2.attributes)

    def test_observation_with_references(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Befund", attributes={"value": 4.2},
                references={"target-id-1": EventRelation.OBSERVATION_OF,
                            "target-id-2": EventRelation.CONFIRMS})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        self.assertEqual(e.references, e2.references)

    def test_confidence_below_one(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Vermutung", attributes={"value": 4.2}, confidence=0.7)
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        self.assertAlmostEqual(e2.confidence, 0.7)

    def test_event_id_preserved(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Test", attributes={"value": 1.0})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        self.assertEqual(e.event_id, e2.event_id)

    def test_stay_period_preserved(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Test", attributes={"value": 1.0})
        e2 = from_fhir(to_fhir(e, resource_type="Observation"))
        self.assertEqual(e.stay_start, e2.stay_start)
        self.assertEqual(e.stay_end, e2.stay_end)


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestConditionRoundTrip(unittest.TestCase):

    def test_simple_condition(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Sepsis", attributes={"severity": "severe"})
        e2 = from_fhir(to_fhir(e, resource_type="Condition"))
        _assert_equivalent(self, e, e2)
        self.assertEqual(e2.attributes.get("severity"), "severe")

    def test_condition_with_evidence(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Sepsis", attributes={"severity": "moderate"},
                references={"laktat-id": EventRelation.CONFIRMS})
        e2 = from_fhir(to_fhir(e, resource_type="Condition"))
        self.assertEqual(e.references, e2.references)


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestMedicationAdministrationRoundTrip(unittest.TestCase):

    def test_simple_medication(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Antibiotikum", attributes={
            "atc_code": "J01DH02", "dose": 1000.0, "unit": "mg", "route": "iv"
        })
        e2 = from_fhir(to_fhir(e, resource_type="MedicationAdministration"))
        _assert_equivalent(self, e, e2)
        self.assertEqual(e2.attributes["atc_code"], "J01DH02")
        self.assertAlmostEqual(e2.attributes["dose"], 1000.0)
        self.assertEqual(e2.attributes["route"], "iv")

    def test_medication_with_reason(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("Antibiotikum",
                attributes={"atc_code": "J01DH02", "dose": 500.0, "unit": "mg"},
                references={"sepsis-id": EventRelation.RESPONSE_TO})
        e2 = from_fhir(to_fhir(e, resource_type="MedicationAdministration"))
        self.assertEqual(e.references, e2.references)


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestProcedureRoundTrip(unittest.TestCase):

    def test_simple_procedure(self):
        from aion.fhir import to_fhir, from_fhir
        e = _ev("ZVK_Anlage", attributes={"site": "v_jugularis"})
        e2 = from_fhir(to_fhir(e, resource_type="Procedure"))
        _assert_equivalent(self, e, e2)
        self.assertEqual(e2.attributes.get("site"), "v_jugularis")


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestBundleOperations(unittest.TestCase):

    def setUp(self):
        from aion import TypeHierarchy
        self.h = TypeHierarchy()
        self.h.add_type("Diagnose", fhir_resource="Condition")
        self.h.add_type("Beobachtung", fhir_resource="Observation")
        self.h.add_type("Medikation", fhir_resource="MedicationAdministration")
        self.h.add_type("Sepsis", parent="Diagnose")
        self.h.add_type("Laktatmessung", parent="Beobachtung")
        self.h.add_type("Antibiotikum", parent="Medikation")

    def test_bundle_create_and_parse(self):
        from aion.fhir import to_fhir_bundle, from_fhir_bundle
        events_in = [
            _ev("Laktatmessung", attributes={"value": 4.2, "unit": "mmol/L"}),
            _ev("Sepsis", attributes={"severity": "severe"}),
        ]
        bundle = to_fhir_bundle(events_in, type_hierarchy=self.h)
        self.assertEqual(bundle.type, "collection")
        self.assertEqual(len(bundle.entry), 2)
        events_out = from_fhir_bundle(bundle)
        self.assertEqual(len(events_out), 2)

    def test_bundle_resource_type_from_hierarchy(self):
        """fhir_resource aus Vorfahren wird geerbt."""
        from aion.fhir import to_fhir_bundle
        events = [_ev("Sepsis", attributes={"severity": "moderate"})]
        bundle = to_fhir_bundle(events, type_hierarchy=self.h)
        self.assertEqual(type(bundle.entry[0].resource).__name__, "Condition")

    def test_bundle_json_roundtrip(self):
        from aion.fhir import to_fhir_bundle, bundle_to_json, bundle_from_json, from_fhir_bundle
        events_in = [
            _ev("Laktatmessung", attributes={"value": 4.2, "unit": "mmol/L"}),
            _ev("Sepsis", attributes={"severity": "severe"},
                references={"some-id": EventRelation.CONFIRMS}),
        ]
        bundle = to_fhir_bundle(events_in, type_hierarchy=self.h)
        text = bundle_to_json(bundle)
        bundle2 = bundle_from_json(text)
        events_out = from_fhir_bundle(bundle2)
        self.assertEqual(len(events_out), len(events_in))

    def test_bundle_skips_unsupported_resources(self):
        """Patient-Resource im Bundle wird ignoriert, Rest läuft durch."""
        from fhir.resources.bundle import Bundle, BundleEntry
        from fhir.resources.patient import Patient
        from aion.fhir import from_fhir_bundle, to_fhir

        obs_event = _ev("Laktatmessung", attributes={"value": 4.2, "unit": "mmol/L"})
        obs = to_fhir(obs_event, resource_type="Observation")

        patient = Patient(id="P-42")  # Nicht unterstützt
        bundle = Bundle(
            type="collection",
            entry=[
                BundleEntry(resource=patient, fullUrl="urn:uuid:patient-1"),
                BundleEntry(resource=obs, fullUrl=f"urn:uuid:{obs.id}"),
            ],
        )
        events = from_fhir_bundle(bundle)
        self.assertEqual(len(events), 1)  # Nur die Observation
        self.assertEqual(events[0].event_type, "Laktatmessung")


@unittest.skipUnless(HAS_FHIR, "fhir.resources nicht installiert")
class TestAutoResourceTypeGuess(unittest.TestCase):

    def test_guess_diagnose_to_condition(self):
        from aion.fhir.codes import guess_resource_type
        self.assertEqual(guess_resource_type("Sepsis_Diagnose"), "Condition")
        self.assertEqual(guess_resource_type("Diagnosis_X"), "Condition")

    def test_guess_observation_default(self):
        from aion.fhir.codes import guess_resource_type
        self.assertEqual(guess_resource_type("WeirdName"), "Observation")

    def test_guess_medication(self):
        from aion.fhir.codes import guess_resource_type
        self.assertEqual(guess_resource_type("Medikation_AB"), "MedicationAdministration")


class TestFhirAvailability(unittest.TestCase):

    def test_has_fhir_returns_bool(self):
        from aion.fhir import has_fhir
        self.assertIsInstance(has_fhir(), bool)

    def test_lazy_import_error_message(self):
        """Wenn fhir.resources fehlt, MUSS eine sprechende ImportError kommen."""
        from aion.fhir.mapper import _require_fhir
        if HAS_FHIR:
            self.assertTrue(_require_fhir())  # darf nicht werfen
        else:
            with self.assertRaises(ImportError) as ctx:
                _require_fhir()
            self.assertIn("fhir.resources", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
