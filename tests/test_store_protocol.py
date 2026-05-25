# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Tests für aion.persistence.store — Storage-Abstraction-Layer."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from aion import ClinicalEvent
from aion.config import AionConfig, StorageConfig
from aion.persistence.store import EventStore, create_event_store
from aion.persistence.sqlite_store import SQLiteEventStore
from aion.persistence.postgres_store import PostgreSQLEventStore


class TestProtocolConformance(unittest.TestCase):
    """SQLiteEventStore muss strukturell EventStore erfüllen."""

    def test_sqlite_is_eventstore(self):
        store = SQLiteEventStore(":memory:")
        try:
            self.assertIsInstance(store, EventStore)
        finally:
            store.close()

    def test_postgres_stub_is_eventstore(self):
        store = PostgreSQLEventStore("postgresql://x@y/z")
        # Auch der Stub erfüllt das Protocol strukturell
        self.assertIsInstance(store, EventStore)


class TestFactory(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-store-factory-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        # Globalen Config-Singleton zurücksetzen, damit Tests nicht
        # gegenseitig beeinflussen
        from aion.config import reset_config
        reset_config()

    def test_factory_returns_sqlite_for_filepath(self):
        cfg = AionConfig(storage=StorageConfig(database=":memory:"))
        store = create_event_store(cfg)
        try:
            self.assertIsInstance(store, SQLiteEventStore)
        finally:
            store.close()

    def test_factory_returns_postgres_for_postgresql_url(self):
        cfg = AionConfig(storage=StorageConfig(
            database="postgresql://user:pass@host/db"
        ))
        store = create_event_store(cfg)
        self.assertIsInstance(store, PostgreSQLEventStore)

    def test_factory_returns_postgres_for_postgres_url(self):
        """`postgres://` ohne `ql` wird auch akzeptiert."""
        cfg = AionConfig(storage=StorageConfig(
            database="postgres://user@host/db"
        ))
        store = create_event_store(cfg)
        self.assertIsInstance(store, PostgreSQLEventStore)

    def test_factory_uses_global_config_when_none(self):
        from aion.config import set_config
        set_config(AionConfig(storage=StorageConfig(database=":memory:")))
        store = create_event_store()  # Kein cfg-Argument
        try:
            self.assertIsInstance(store, SQLiteEventStore)
        finally:
            store.close()

    def test_factory_database_argument_overrides_config(self):
        cfg = AionConfig(storage=StorageConfig(
            database="postgresql://will-be-ignored@host/db"
        ))
        store = create_event_store(cfg, database=":memory:")
        try:
            self.assertIsInstance(store, SQLiteEventStore)
        finally:
            store.close()


class TestPostgresStub(unittest.TestCase):
    """Stub-Verhalten — alle Methoden werfen NotImplementedError mit
    klarer Roadmap-Botschaft."""

    def setUp(self):
        self.store = PostgreSQLEventStore("postgresql://test@host/db")

    def test_connect_raises(self):
        with self.assertRaises(NotImplementedError) as ctx:
            self.store.connect()
        self.assertIn("1.7.0", str(ctx.exception))
        self.assertIn("Workaround", str(ctx.exception))

    def test_close_is_noop(self):
        """close() darf KEIN NotImplementedError werfen — Idempotenz."""
        self.store.close()  # darf nicht crashen

    def test_add_raises(self):
        ev = ClinicalEvent(
            patient_id="P-1", event_type="Test",
            t_start=datetime.now(), t_end=datetime.now(),
            stay_start=datetime.now(),
            stay_end=datetime.now() + timedelta(hours=1),
        )
        with self.assertRaises(NotImplementedError):
            self.store.add(ev)

    def test_count_raises(self):
        with self.assertRaises(NotImplementedError):
            self.store.count()

    def test_get_raises(self):
        with self.assertRaises(NotImplementedError):
            self.store.get("evt-1")

    def test_all_methods_raise(self):
        """Sicherstellen, dass JEDE Datenmethode NotImplementedError wirft."""
        methods_to_test = [
            ("add_many", ([],)),
            ("update", (None,)),
            ("delete", ("evt-1",)),
            ("all", ()),
            ("find_by_patient", ("P-1",)),
            ("find_by_type", ("X",)),
            ("references_of", ("evt-1",)),
            ("referenced_by", ("evt-1",)),
        ]
        for method_name, args in methods_to_test:
            with self.subTest(method=method_name):
                with self.assertRaises(NotImplementedError):
                    getattr(self.store, method_name)(*args)


class TestSqliteRoundtripViaProtocol(unittest.TestCase):
    """Smoke-Test: SQLite-Backend funktioniert weiterhin via Factory."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-store-roundtrip-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        from aion.config import reset_config
        reset_config()

    def test_factory_sqlite_full_roundtrip(self):
        db = str(Path(self._tmpdir) / "test.db")
        cfg = AionConfig(storage=StorageConfig(database=db))

        base = datetime(2026, 4, 1, 10, 0)
        ev = ClinicalEvent(
            patient_id="P-001", event_type="Aufnahme",
            t_start=base, t_end=base,
            stay_start=base, stay_end=base + timedelta(days=1),
        )

        # Schreiben über Factory
        with create_event_store(cfg) as store:
            store.add(ev)

        # Lesen über separate Factory-Instanz (DB-Persistenz)
        with create_event_store(cfg) as store2:
            self.assertEqual(store2.count(), 1)
            events = store2.find_by_patient("P-001")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "Aufnahme")


if __name__ == "__main__":
    unittest.main()
