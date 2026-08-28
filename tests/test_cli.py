# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.cli (Kommandozeilen-Werkzeug)."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from aion import has_fhir
from aion.cli import main, build_parser


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Helper: ruft CLI auf, captured stdout/stderr."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        try:
            code = main(args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out_buf.getvalue(), err_buf.getvalue()


class TestParserConstruction(unittest.TestCase):
    """Argparser kann gebaut werden, alle Subcommands registriert."""

    def test_build_parser(self):
        p = build_parser()
        self.assertIsNotNone(p)

    def test_all_subcommands_registered(self):
        p = build_parser()
        # Subparser-Action finden
        sub_actions = [a for a in p._actions if hasattr(a, "choices") and a.choices]
        self.assertTrue(sub_actions, "Subparser fehlen")
        choices = sub_actions[0].choices
        for cmd in ["validate", "types", "stats", "mine", "import", "export"]:
            self.assertIn(cmd, choices, f"Subcommand {cmd} fehlt")


class TestValidateCommand(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-cli-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_validate_existing_schema(self):
        """clinical_base.yaml validiert sauber durch."""
        schema = Path(__file__).resolve().parent.parent / "schemas" / "clinical_base.yaml"
        if not schema.exists():
            self.skipTest("clinical_base.yaml nicht gefunden")
        code, out, err = run_cli(["validate", str(schema)])
        self.assertEqual(code, 0)
        self.assertIn("✓", out)
        self.assertIn("Typen", out)

    def test_validate_missing_file(self):
        code, out, err = run_cli(["validate", "/tmp/nonexistent.yaml"])
        self.assertEqual(code, 1)
        self.assertIn("FEHLER", err)


class TestStatsCommand(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-cli-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_stats_on_empty_db(self):
        from aion import SQLiteEventStore
        db = str(Path(self._tmpdir) / "empty.db")
        with SQLiteEventStore(db):
            pass  # Erstellt leere DB

        code, out, err = run_cli(["stats", db])
        self.assertEqual(code, 0)
        self.assertIn("leer", out.lower())

    def test_stats_with_events(self):
        from datetime import datetime, timedelta
        from aion import SQLiteEventStore, ClinicalEvent

        db = str(Path(self._tmpdir) / "test.db")
        base = datetime(2026, 4, 1, 10, 0)
        with SQLiteEventStore(db) as store:
            for i in range(5):
                store.add(ClinicalEvent(
                    patient_id=f"P-{i:03d}",
                    event_type="Aufnahme",
                    t_start=base, t_end=base,
                    stay_start=base, stay_end=base + timedelta(days=1),
                ))
        code, out, err = run_cli(["stats", db])
        self.assertEqual(code, 0)
        self.assertIn("5", out)  # Anzahl-Events
        self.assertIn("Aufnahme", out)

    def test_stats_missing_db(self):
        code, out, err = run_cli(["stats", "/tmp/nonexistent.db"])
        self.assertEqual(code, 1)


class TestMineCommand(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-cli-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_mine_finds_pattern(self):
        from datetime import datetime, timedelta
        from aion import SQLiteEventStore, ClinicalEvent

        db = str(Path(self._tmpdir) / "mine.db")
        base = datetime(2026, 4, 1, 10, 0)
        with SQLiteEventStore(db) as store:
            for pid in ["P-1", "P-2", "P-3"]:
                for offset, typ in enumerate(["A", "B", "C"]):
                    store.add(ClinicalEvent(
                        patient_id=pid, event_type=typ,
                        t_start=base + timedelta(hours=offset),
                        t_end=base + timedelta(hours=offset),
                        stay_start=base, stay_end=base + timedelta(days=1),
                    ))
        code, out, err = run_cli(["mine", db, "--min-support", "0.5"])
        self.assertEqual(code, 0)
        self.assertIn("A → B → C", out)


@unittest.skipUnless(has_fhir(), "fhir.resources nicht installiert")
class TestImportExportCommand(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-cli-test-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_import_export_roundtrip(self):
        from datetime import datetime, timedelta
        from aion import ClinicalEvent
        from aion.fhir import to_fhir_bundle
        from aion.fhir.bundle import bundle_to_file

        # Bundle erzeugen
        bundle_path = str(Path(self._tmpdir) / "in.json")
        events = []
        base = datetime(2026, 4, 1, 10, 0)
        for typ in ["Aufnahme", "Fieber"]:
            events.append(ClinicalEvent(
                patient_id="P-001", event_type=typ,
                t_start=base, t_end=base,
                stay_start=base, stay_end=base + timedelta(days=1),
            ))
        bundle = to_fhir_bundle(events)
        bundle_to_file(bundle, bundle_path)

        # Import
        db_path = str(Path(self._tmpdir) / "test.db")
        code, out, _ = run_cli(["import", bundle_path, "--db", db_path])
        self.assertEqual(code, 0)
        self.assertIn("2 Events", out)

        # Export Round-Trip
        out_path = str(Path(self._tmpdir) / "out.json")
        code, out, _ = run_cli(["export", db_path, "--out", out_path])
        self.assertEqual(code, 0)
        self.assertTrue(Path(out_path).exists())


class TestVersionFlag(unittest.TestCase):

    def test_version_prints_aion_version(self):
        # --version löst SystemExit aus, abfangen
        code, out, err = run_cli(["--version"])
        # Ausgabe kann auf stdout oder stderr landen je nach Python-Version
        combined = out + err
        from aion import __version__
        self.assertIn(__version__, combined)


if __name__ == "__main__":
    unittest.main()
