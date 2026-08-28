# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.audit — Audit-Trail."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aion.audit import AuditLog, AuditAction


class TestAuditBasics(unittest.TestCase):

    def setUp(self):
        self.audit = AuditLog(":memory:")

    def tearDown(self):
        self.audit.close()

    def test_record_returns_id(self):
        audit_id = self.audit.record(AuditAction.READ, user="testuser")
        self.assertIsInstance(audit_id, int)
        self.assertGreater(audit_id, 0)

    def test_count_increments(self):
        self.assertEqual(self.audit.count(), 0)
        self.audit.record(AuditAction.READ, user="user1")
        self.audit.record(AuditAction.CREATE, user="user2")
        self.assertEqual(self.audit.count(), 2)

    def test_action_can_be_string_or_enum(self):
        id1 = self.audit.record(AuditAction.READ)
        id2 = self.audit.record("read")
        # Beide Wege müssen dieselbe Aktion erzeugen
        rows = self.audit.query()
        actions = {r["action"] for r in rows}
        self.assertEqual(actions, {"read"})


class TestAppendOnly(unittest.TestCase):
    """Audit darf NICHT geändert oder gelöscht werden."""

    def setUp(self):
        self.audit = AuditLog(":memory:")
        self.audit.record(AuditAction.CREATE, user="testuser")

    def tearDown(self):
        self.audit.close()

    def test_update_is_forbidden(self):
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.audit._conn.execute(
                "UPDATE audit_log SET user = 'fake' WHERE audit_id = 1"
            )
            self.audit._conn.commit()
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_delete_is_forbidden(self):
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.audit._conn.execute("DELETE FROM audit_log WHERE audit_id = 1")
            self.audit._conn.commit()
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_insert_is_allowed(self):
        # INSERT muss weiterhin gehen
        before = self.audit.count()
        self.audit.record(AuditAction.UPDATE, user="other")
        self.assertEqual(self.audit.count(), before + 1)


class TestPatientPseudonymization(unittest.TestCase):
    """Patient-IDs dürfen NIE im Klartext im Audit-Log landen."""

    def setUp(self):
        self.audit = AuditLog(":memory:")

    def tearDown(self):
        self.audit.close()

    def test_patient_id_is_hashed(self):
        self.audit.record(
            AuditAction.READ, user="dr.mueller",
            resource_type="ClinicalEvent",
            patient_id="P-12345",
        )
        rows = self.audit.query()
        self.assertEqual(len(rows), 1)
        # patient_hash darf NICHT der Klartext sein
        self.assertNotEqual(rows[0]["patient_hash"], "P-12345")
        self.assertNotIn("12345", rows[0]["patient_hash"])
        # Aber das Pseudonym-Format
        self.assertTrue(rows[0]["patient_hash"].startswith("p#"))

    def test_query_by_patient_id_works_via_hash(self):
        """Suche mit Klartext-ID muss den hashed Eintrag finden."""
        self.audit.record(AuditAction.READ, patient_id="P-12345")
        self.audit.record(AuditAction.READ, patient_id="P-OTHER")

        results = self.audit.query(patient_id="P-12345")
        self.assertEqual(len(results), 1)
        # Der gefundene Eintrag betrifft P-12345 (hashed)
        from aion.core.privacy import pseudonymize
        self.assertEqual(results[0]["patient_hash"], pseudonymize("P-12345"))

    def test_no_patient_id_when_unset(self):
        self.audit.record(AuditAction.READ)
        rows = self.audit.query()
        self.assertIsNone(rows[0]["patient_hash"])


class TestQueryFilters(unittest.TestCase):

    def setUp(self):
        self.audit = AuditLog(":memory:")
        self.audit.record(AuditAction.READ, user="alice")
        self.audit.record(AuditAction.READ, user="bob")
        self.audit.record(AuditAction.CREATE, user="alice")
        self.audit.record(AuditAction.LOGIN_FAILED, user="mallory", success=False)

    def tearDown(self):
        self.audit.close()

    def test_filter_by_action(self):
        rows = self.audit.query(action="read")
        self.assertEqual(len(rows), 2)

    def test_filter_by_user(self):
        rows = self.audit.query(user="alice")
        self.assertEqual(len(rows), 2)

    def test_filter_by_success_false(self):
        rows = self.audit.query(success=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user"], "mallory")

    def test_filter_combined(self):
        rows = self.audit.query(action="read", user="alice")
        self.assertEqual(len(rows), 1)

    def test_filter_by_time_window(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=1)
        rows = self.audit.query(since=future)
        self.assertEqual(len(rows), 0)

    def test_results_sorted_descending(self):
        """Neueste zuerst."""
        rows = self.audit.query()
        ids = [r["audit_id"] for r in rows]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_limit_applied(self):
        rows = self.audit.query(limit=2)
        self.assertEqual(len(rows), 2)


class TestPersistence(unittest.TestCase):
    """Audit-Einträge bleiben über Reconnect erhalten."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-audit-test-")
        self.path = str(Path(self._tmpdir) / "audit.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_roundtrip_to_file(self):
        with AuditLog(self.path) as a:
            a.record(AuditAction.LOGIN, user="alice", ip="10.0.0.1")
            a.record(AuditAction.READ, user="alice", patient_id="P-001")
            self.assertEqual(a.count(), 2)

        # Reopen
        with AuditLog(self.path) as a2:
            self.assertEqual(a2.count(), 2)
            rows = a2.query()
            self.assertEqual(rows[0]["action"], "read")
            self.assertEqual(rows[1]["action"], "login")


class TestExport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-audit-test-")
        self.audit = AuditLog(":memory:")

    def tearDown(self):
        self.audit.close()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_export_csv(self):
        self.audit.record(AuditAction.LOGIN, user="alice", ip="10.0.0.1")
        self.audit.record(AuditAction.READ, user="alice", patient_id="P-001")

        csv_path = Path(self._tmpdir) / "export.csv"
        n = self.audit.export_csv(csv_path)

        self.assertEqual(n, 2)
        self.assertTrue(csv_path.exists())
        content = csv_path.read_text(encoding="utf-8")
        self.assertIn("alice", content)
        self.assertIn("login", content)
        # Klartext-Patient-ID darf NICHT im Export sein
        self.assertNotIn("P-001", content)


class TestThreadSafety(unittest.TestCase):

    def test_concurrent_inserts(self):
        """Mehrere Threads schreiben gleichzeitig — keine Verluste."""
        import threading
        audit = AuditLog(":memory:")
        n_threads = 5
        n_per_thread = 20

        def writer(tid: int) -> None:
            for i in range(n_per_thread):
                audit.record(AuditAction.READ, user=f"user-{tid}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
        for t in threads: t.start()
        for t in threads: t.join()

        self.assertEqual(audit.count(), n_threads * n_per_thread)
        audit.close()


if __name__ == "__main__":
    unittest.main()
