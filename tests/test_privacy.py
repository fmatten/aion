# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Tests für aion.core.privacy."""
import unittest

from aion.core.privacy import (
    pseudonymize, safe_path, fingerprint_dict, reset_session_salt,
)


class TestPseudonymize(unittest.TestCase):

    def test_basic_format(self):
        result = pseudonymize("P-12345")
        self.assertTrue(result.startswith("p#"))
        # p# + length=8 Zeichen
        self.assertEqual(len(result), 10)

    def test_stable_within_session(self):
        """Gleiche Eingabe → gleiches Pseudonym in derselben Session."""
        a = pseudonymize("P-001")
        b = pseudonymize("P-001")
        self.assertEqual(a, b)

    def test_different_inputs_different_outputs(self):
        a = pseudonymize("P-001")
        b = pseudonymize("P-002")
        self.assertNotEqual(a, b)

    def test_different_salts_different_outputs(self):
        """Nach reset_session_salt() liefert dieselbe ID ein anderes Pseudonym."""
        a = pseudonymize("P-001")
        reset_session_salt()
        b = pseudonymize("P-001")
        # Sehr selten kann das zufällig kollidieren, aber bei 8 Hex-Zeichen
        # ist die Wahrscheinlichkeit < 1 in 4 Milliarden.
        self.assertNotEqual(a, b)

    def test_none_input(self):
        self.assertEqual(pseudonymize(None), "p#none")

    def test_int_input(self):
        # IDs können auch numerisch sein
        result = pseudonymize(12345)
        self.assertTrue(result.startswith("p#"))

    def test_no_plaintext_id_in_output(self):
        """Pseudonym darf keine Substring der Original-ID enthalten."""
        original = "PATIENT-ABCDEF"
        result = pseudonymize(original)
        for chunk_len in (4, 6, 8):
            for i in range(len(original) - chunk_len + 1):
                substring = original[i:i + chunk_len]
                self.assertNotIn(substring.lower(), result.lower())


class TestSafePath(unittest.TestCase):

    def test_full_path_reduced_to_basename(self):
        self.assertEqual(safe_path("/home/dr-mueller/klinik/patients.db"),
                         "patients.db")

    def test_windows_path(self):
        self.assertEqual(safe_path("C:\\Users\\Admin\\data.db"), "data.db")

    def test_in_memory(self):
        self.assertEqual(safe_path(":memory:"), ":memory:")

    def test_none(self):
        self.assertEqual(safe_path(None), "<none>")

    def test_no_directory_info_leaks(self):
        sensitive = "/home/dr-mueller/Sepsis-Studie/Geheimprojekt/data.db"
        result = safe_path(sensitive)
        self.assertNotIn("dr-mueller", result)
        self.assertNotIn("Geheimprojekt", result)
        self.assertNotIn("Sepsis-Studie", result)


class TestFingerprintDict(unittest.TestCase):

    def test_keys_only_no_values(self):
        d = {"patient_id": "P-001", "lactate": 4.2, "stemi": True}
        result = fingerprint_dict(d)
        self.assertIn("patient_id", result)
        self.assertIn("lactate", result)
        # Werte dürfen NICHT auftauchen
        self.assertNotIn("P-001", result)
        self.assertNotIn("4.2", result)
        self.assertNotIn("True", result)

    def test_empty(self):
        self.assertEqual(fingerprint_dict({}), "{}")
        self.assertEqual(fingerprint_dict(None), "{}")

    def test_truncation_of_many_keys(self):
        d = {f"k{i}": i for i in range(20)}
        result = fingerprint_dict(d, max_keys=5)
        self.assertIn("more", result)
        self.assertIn("+15", result)


if __name__ == "__main__":
    unittest.main()
