# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für Schema-Loader (YAML)."""
import os
import tempfile
import unittest

try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from aion.core.types import TypeHierarchy


@unittest.skipUnless(HAS_YAML, "PyYAML nicht installiert")
class TestSchemaLoader(unittest.TestCase):

    def test_load_clinical_base(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "schemas", "clinical_base.yaml"
        )
        path = os.path.normpath(path)
        h = TypeHierarchy.from_yaml(path)
        self.assertIn("Diagnose", h)
        self.assertIn("Herzinfarkt", h)
        self.assertTrue(h.is_subtype("Herzinfarkt", "Diagnose"))
        self.assertTrue(h.is_subtype("Sepsis", "Diagnose"))

    def test_load_cardiology_extension(self):
        """Kardiologie-Schema lädt zusammen mit clinical_base."""
        from aion import check_inheritance_conflicts

        schemas_dir = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "schemas"
        ))
        # Beide Schemata in eine Hierarchie laden (kombinierter Use-Case)
        h = TypeHierarchy()
        for fname in ("clinical_base.yaml", "cardiology_extension.yaml"):
            with open(os.path.join(schemas_dir, fname), encoding="utf-8") as f:
                data = yaml.safe_load(f)
            entries = data.get("types", [])
            by_name = {e["name"]: e for e in entries}
            visited: set = set()
            ordered: list = []

            def visit(name):
                if name in visited or name not in by_name:
                    return
                visited.add(name)
                p = by_name[name].get("parent")
                if p and p in by_name:
                    visit(p)
                ordered.append(by_name[name])

            for e in entries:
                visit(e["name"])
            for e in ordered:
                if e["name"] in h:
                    continue
                h.add_type(
                    name=e["name"],
                    parent=e.get("parent"),
                    fhir_resource=e.get("fhir"),
                    attributes=e.get("attributes", {}) or {},
                    description=e.get("description", "") or "",
                )

        # Kardiologische Spezialdiagnosen vorhanden
        self.assertIn("STEMI", h)
        self.assertIn("NSTEMI", h)
        self.assertIn("InstabileAngina", h)
        # STEMI ist transitiv eine Diagnose
        self.assertTrue(h.is_subtype("STEMI", "AkutesKoronarsyndrom"))
        self.assertTrue(h.is_subtype("STEMI", "Diagnose"))
        # PCI ist eine Prozedur
        self.assertTrue(h.is_subtype("PCI", "Prozedur"))
        # Konsistenz-Check muss grün sein
        report = check_inheritance_conflicts(h)
        self.assertTrue(report.ok, msg=report.summary())

    def test_topo_sort_handles_unsorted(self):
        """Schema mit Kindern vor Eltern muss korrekt geladen werden."""
        import yaml as _yaml
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            _yaml.safe_dump({
                "types": [
                    {"name": "C", "parent": "B"},
                    {"name": "A"},
                    {"name": "B", "parent": "A"},
                ]
            }, f)
            path = f.name
        try:
            h = TypeHierarchy.from_yaml(path)
            self.assertTrue(h.is_subtype("C", "A"))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
