# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.synthea-Importer."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aion import has_synthea
from aion.synthea import (
    synthea_import_bundle,
    synthea_import_directory,
    SUPPORTED_RESOURCE_TYPES,
)
from aion.synthea.codes import (
    DEFAULT_LOINC_MAP, DEFAULT_SNOMED_MAP,
    lookup_code, fallback_type_name,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "synthea" / "Patient_001.json"


class TestApiAvailability(unittest.TestCase):
    def test_has_synthea_is_true(self):
        # Synthea ist stdlib-only, also immer da
        self.assertTrue(has_synthea())


class TestCodeMapping(unittest.TestCase):

    def test_loinc_temperature(self):
        self.assertEqual(lookup_code("8310-5", "http://loinc.org"), "Körpertemperatur")

    def test_snomed_emergency(self):
        self.assertEqual(lookup_code("50849002", "http://snomed.info/sct"),
                         "Notaufnahme")

    def test_unknown_code_returns_none(self):
        self.assertIsNone(lookup_code("999999999"))

    def test_extra_map_overrides_default(self):
        extra = {"8310-5": "Mein_Custom_Typ"}
        self.assertEqual(lookup_code("8310-5", "http://loinc.org",
                                     extra_map=extra), "Mein_Custom_Typ")

    def test_no_system_still_finds_code(self):
        """Auch ohne system-Hinweis wird gefunden."""
        self.assertEqual(lookup_code("8310-5"), "Körpertemperatur")

    def test_fallback_type_name(self):
        self.assertEqual(fallback_type_name("Observation"), "FHIR_Observation")
        self.assertEqual(fallback_type_name("Condition"), "FHIR_Condition")

    def test_default_maps_are_dicts(self):
        self.assertIsInstance(DEFAULT_LOINC_MAP, dict)
        self.assertIsInstance(DEFAULT_SNOMED_MAP, dict)
        # Mindestens 10 Mappings je
        self.assertGreaterEqual(len(DEFAULT_LOINC_MAP), 10)
        self.assertGreaterEqual(len(DEFAULT_SNOMED_MAP), 5)


class TestBundleImport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not FIXTURE_PATH.exists():
            raise unittest.SkipTest(f"Fixture fehlt: {FIXTURE_PATH}")

    def test_imports_all_supported_resources(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        # Encounter (= Aufnahme), 3 Observations, 1 Condition,
        # 1 Procedure, 1 MedicationRequest = 7 Events
        self.assertEqual(len(events), 7)

    def test_events_chronologically_sorted(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        for i in range(1, len(events)):
            self.assertLessEqual(events[i-1].t_start, events[i].t_start)

    def test_known_codes_mapped(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        types = {e.event_type for e in events}
        # Körpertemperatur, Herzfrequenz, Glucose sollen gemappt sein
        self.assertIn("Körpertemperatur", types)
        self.assertIn("Herzfrequenz", types)
        self.assertIn("Glucose", types)
        # Notaufnahme aus Encounter type
        self.assertIn("Notaufnahme", types)

    def test_unknown_codes_get_fallback(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        types = {e.event_type for e in events}
        # Sepsis-Code ist NICHT im Default-Mapping (unstrittiger Anspruch)
        self.assertIn("FHIR_Condition", types)
        self.assertIn("FHIR_Procedure", types)
        self.assertIn("FHIR_MedicationRequest", types)

    def test_fhir_codes_preserved_in_attributes(self):
        """Auch ohne Mapping bleibt der FHIR-Code als Attribut erhalten."""
        events = synthea_import_bundle(FIXTURE_PATH)
        condition = next(e for e in events if e.event_type == "FHIR_Condition")
        self.assertEqual(condition.attributes.get("fhir_code"), "91302008")
        self.assertIn("snomed", condition.attributes.get("fhir_system", ""))

    def test_observation_value_extracted(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        temp = next(e for e in events if e.event_type == "Körpertemperatur")
        self.assertEqual(temp.attributes["value"], 39.2)
        self.assertEqual(temp.attributes["unit"], "Cel")

    def test_encounter_period_used_as_stay(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        # Alle Events innerhalb des Encounters sollten dieselbe stay-Periode haben
        non_encounter_events = [
            e for e in events if e.event_type not in ("Notaufnahme",)
        ]
        if not non_encounter_events:
            self.skipTest("kein nicht-Encounter-Event")
        first = non_encounter_events[0]
        # Encounter geht von 08:30 bis 19. April 16:00
        self.assertEqual(first.stay_start, datetime(2026, 4, 15, 8, 30))
        self.assertEqual(first.stay_end, datetime(2026, 4, 19, 16, 0))

    def test_patient_id_extracted(self):
        events = synthea_import_bundle(FIXTURE_PATH)
        ids = {e.patient_id for e in events}
        self.assertEqual(ids, {"patient-001"})

    def test_extra_code_map_applied(self):
        """Custom-Mapping kann unbekannte Codes mappen."""
        # SNOMED 91302008 = Sepsis
        events = synthea_import_bundle(
            FIXTURE_PATH,
            code_map={"91302008": "Sepsis"},
        )
        types = {e.event_type for e in events}
        self.assertIn("Sepsis", types)
        # Die FHIR_Condition-Fallback-Klasse darf jetzt nicht mehr da sein
        self.assertNotIn("FHIR_Condition", types)

    def test_include_encounters_false(self):
        events = synthea_import_bundle(FIXTURE_PATH, include_encounters=False)
        types = {e.event_type for e in events}
        self.assertNotIn("Notaufnahme", types)
        self.assertNotIn("Aufnahme", types)


class TestErrorHandling(unittest.TestCase):

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            synthea_import_bundle("/tmp/does-not-exist.json")

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("kein gültiges json {{{")
            path = f.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                synthea_import_bundle(path)
        finally:
            Path(path).unlink()

    def test_not_a_bundle(self):
        """Wirft ValueError, wenn resourceType nicht Bundle ist."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"resourceType": "Patient"}, f)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                synthea_import_bundle(path)
        finally:
            Path(path).unlink()


class TestDirectoryImport(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="aion-synthea-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _copy_fixture(self, n: int):
        """Legt n Kopien des Fixture-Bundles an."""
        for i in range(n):
            target = Path(self.tmpdir) / f"Patient_{i:03d}.json"
            target.write_text(FIXTURE_PATH.read_text(encoding="utf-8"),
                              encoding="utf-8")

    def test_directory_with_three_bundles(self):
        self._copy_fixture(3)
        events = synthea_import_directory(self.tmpdir)
        # 3 Bundles × 7 Events = 21
        self.assertEqual(len(events), 21)

    def test_limit_parameter(self):
        self._copy_fixture(5)
        events = synthea_import_directory(self.tmpdir, limit=2)
        self.assertEqual(len(events), 14)  # 2 Bundles × 7

    def test_directory_not_found(self):
        with self.assertRaises(FileNotFoundError):
            synthea_import_directory("/tmp/nonexistent-dir-xyz/")

    def test_skips_invalid_bundles(self):
        """Defekte Bundles werden geloggt aber nicht crashen das ganze Verzeichnis."""
        self._copy_fixture(2)
        # Ein invalides Bundle dazu
        bad = Path(self.tmpdir) / "broken.json"
        bad.write_text("not json", encoding="utf-8")

        events = synthea_import_directory(self.tmpdir)
        # Die zwei guten Bundles → 14 Events, das defekte übersprungen
        self.assertEqual(len(events), 14)


class TestSupportedResourceTypes(unittest.TestCase):

    def test_supported_set_documented(self):
        self.assertIsInstance(SUPPORTED_RESOURCE_TYPES, set)
        # Mindestens diese
        for t in ("Encounter", "Condition", "Observation", "Procedure"):
            self.assertIn(t, SUPPORTED_RESOURCE_TYPES)


if __name__ == "__main__":
    unittest.main()
