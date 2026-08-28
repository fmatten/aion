# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für SQLite-Schema-Migration.

1.0.0-Anforderung: Datenbanken, die mit älteren AION-Versionen erstellt
wurden, müssen sich problemlos öffnen und auf das aktuelle Schema heben
lassen. Hier wird das mit synthetisch erzeugten "alten" DBs getestet.
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aion.core.events import ClinicalEvent
from aion.persistence.sqlite_store import SQLiteEventStore


# Schema wie in 0.2.x — KEINE relation-Spalte in event_references
LEGACY_SCHEMA_V02 = """
CREATE TABLE events (
    event_id    TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    t_start     TEXT NOT NULL,
    t_end       TEXT NOT NULL,
    stay_start  TEXT NOT NULL,
    stay_end    TEXT NOT NULL,
    attributes  TEXT NOT NULL DEFAULT '{}',
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX idx_patient_time ON events(patient_id, t_start);
CREATE INDEX idx_event_type   ON events(event_type);
CREATE INDEX idx_t_start      ON events(t_start);

CREATE TABLE event_references (
    event_id  TEXT NOT NULL,
    ref_id    TEXT NOT NULL,
    PRIMARY KEY (event_id, ref_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX idx_ref_id ON event_references(ref_id);
"""


def create_legacy_db(path: str) -> None:
    """Erzeugt eine DB mit altem Schema (0.2.x)."""
    from datetime import timezone
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA_V02)
    # Ein Beispiel-Event mit Referenz
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO events VALUES
           ('evt1', 'P-100', 'Diagnose',
            '2026-01-01T08:00', '2026-01-01T08:00',
            '2026-01-01T07:00', '2026-01-05T12:00',
            '{}', 1.0, ?, ?)""",
        (now, now),
    )
    conn.execute(
        """INSERT INTO events VALUES
           ('evt2', 'P-100', 'Beobachtung',
            '2026-01-01T07:30', '2026-01-01T07:30',
            '2026-01-01T07:00', '2026-01-05T12:00',
            '{}', 1.0, ?, ?)""",
        (now, now),
    )
    # Referenz im alten Schema (ohne relation)
    conn.execute("INSERT INTO event_references (event_id, ref_id) VALUES ('evt1', 'evt2')")
    conn.commit()
    conn.close()


class TestLegacyMigration(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-test-")
        self.db_path = str(Path(self._tmpdir) / "legacy.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_legacy_db_opens_without_error(self):
        """SQLiteEventStore öffnet eine 0.2.x-DB ohne zu crashen."""
        create_legacy_db(self.db_path)
        store = SQLiteEventStore(self.db_path)
        self.assertEqual(store.count(), 2)
        store.close()

    def test_legacy_relation_defaults_to_references(self):
        """Alte Referenzen ohne relation-Wert müssen 'references' bekommen."""
        create_legacy_db(self.db_path)
        with SQLiteEventStore(self.db_path) as store:
            refs = store.references_of("evt1")
            self.assertEqual(refs, {"evt2": "references"})

    def test_migration_idempotent(self):
        """Mehrfaches Öffnen darf keine doppelten Schema-Operationen auslösen."""
        create_legacy_db(self.db_path)
        for _ in range(3):
            store = SQLiteEventStore(self.db_path)
            self.assertEqual(store.count(), 2)
            store.close()

    def test_can_write_after_migration(self):
        """Nach Migration funktionieren neue typisierte Refs."""
        create_legacy_db(self.db_path)
        with SQLiteEventStore(self.db_path) as store:
            from datetime import timedelta
            from aion.core.relations import EventRelation
            now = datetime(2026, 5, 8, 12, 0)
            new_event = ClinicalEvent(
                patient_id="P-100",
                event_type="Medikation",
                t_start=now, t_end=now,
                stay_start=now - timedelta(hours=1),
                stay_end=now + timedelta(days=1),
                references={"evt1": EventRelation.RESPONSE_TO},
            )
            store.add(new_event)
            loaded = store.get(new_event.event_id)
            self.assertEqual(loaded.references, {"evt1": "response_to"})

    def test_legacy_data_not_corrupted(self):
        """Alte Events müssen nach Migration unverändert lesbar sein."""
        create_legacy_db(self.db_path)
        with SQLiteEventStore(self.db_path) as store:
            evt1 = store.get("evt1")
            self.assertIsNotNone(evt1)
            self.assertEqual(evt1.patient_id, "P-100")
            self.assertEqual(evt1.event_type, "Diagnose")

    def test_relation_index_exists_after_migration(self):
        """Performance-Index für Relations muss nach Migration existieren."""
        create_legacy_db(self.db_path)
        with SQLiteEventStore(self.db_path) as store:
            cur = store._conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_relation'"
            )
            self.assertIsNotNone(cur.fetchone(),
                                 "idx_relation muss nach Migration existieren")


if __name__ == "__main__":
    unittest.main()
