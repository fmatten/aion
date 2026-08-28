# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""SQLite-basierter Event-Store für klinische Ereignisse.

Designentscheidungen:
    * Nur sqlite3 aus stdlib — keine SQLAlchemy-Abhängigkeit.
    * Schema:
        events:
            event_id      TEXT PRIMARY KEY
            patient_id    TEXT NOT NULL
            event_type    TEXT NOT NULL
            t_start       TEXT (ISO 8601)
            t_end         TEXT
            stay_start    TEXT
            stay_end      TEXT
            attributes    TEXT  (JSON)
            confidence    REAL
            created_at    TEXT
            updated_at    TEXT
        event_references (event_id, ref_id)  --  ρ ⊆ E

    * Indizes:
        idx_patient_time  (patient_id, t_start)  -- typische klinische Abfrage
        idx_event_type    (event_type)
        idx_t_start       (t_start)

    * WAL-Modus für gleichzeitige Lese-/Schreibzugriffe.
    * Prepared Statements (Schutz gegen SQL-Injection).
    * Bulk-Inserts via executemany.
    * Context-Manager-Support (with-Statement).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from aion.core.events import ClinicalEvent


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
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

CREATE INDEX IF NOT EXISTS idx_patient_time ON events(patient_id, t_start);
CREATE INDEX IF NOT EXISTS idx_event_type   ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_t_start      ON events(t_start);

CREATE TABLE IF NOT EXISTS event_references (
    event_id  TEXT NOT NULL,
    ref_id    TEXT NOT NULL,
    relation  TEXT NOT NULL DEFAULT 'references',
    PRIMARY KEY (event_id, ref_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ref_id    ON event_references(ref_id);
CREATE INDEX IF NOT EXISTS idx_relation  ON event_references(relation);
"""


class SQLiteEventStore:
    """Persistenter Event-Store auf SQLite-Basis.

    Thread-safe via Lock. Verbindung kann pro Instanz oder pro Aufruf erfolgen.
    Beispiel:

        with SQLiteEventStore("clinical.db") as store:
            store.add(event)
            for e in store.find_by_patient("P001"):
                print(e)
    """

    def __init__(self, path: Union[str, Path] = ":memory:", *, wal: bool = True) -> None:
        self.path = str(path)
        self._wal = wal
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self.connect()

    # ── Connection-Management ────────────────────────────────────
    def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        if self._wal and self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")
        # Reihenfolge wichtig:
        # 1. Existierende Tabellen auf aktuelles Schema heben (Migration).
        # 2. Erst dann das aktuelle _SCHEMA ausführen — das enthält Indizes,
        #    die Spalten voraussetzen, die ggf. erst durch Migration entstanden.
        # _SCHEMA ist mit IF NOT EXISTS überall idempotent.
        self._migrate()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate(self) -> None:
        """Fügt fehlende Spalten in vorhandenen Datenbanken nach.

        Notwendig für DBs, die mit aion-clinical < 0.3.0 angelegt wurden.
        Idempotent — kann beliebig oft aufgerufen werden.

        Bei leeren DBs (Tabelle existiert noch nicht) ist nichts zu tun;
        _SCHEMA legt die Tabelle anschließend mit aktuellem Schema an.
        """
        assert self._conn is not None
        # Existiert die Tabelle überhaupt?
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='event_references'"
        )
        if cur.fetchone() is None:
            return  # Leere DB — _SCHEMA legt aktuelle Tabelle an, kein Migrationsbedarf

        cur = self._conn.execute("PRAGMA table_info(event_references)")
        cols = {row["name"] for row in cur.fetchall()}
        if "relation" not in cols:
            self._conn.execute(
                "ALTER TABLE event_references "
                "ADD COLUMN relation TEXT NOT NULL DEFAULT 'references'"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relation ON event_references(relation)"
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "SQLiteEventStore":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomarer Block für mehrere Operationen."""
        assert self._conn is not None
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ── CRUD ──────────────────────────────────────────────────────
    def add(self, event: ClinicalEvent) -> None:
        self._add_many([event])

    def add_many(self, events: Iterable[ClinicalEvent]) -> int:
        events = list(events)
        if not events:
            return 0
        return self._add_many(events)

    def _add_many(self, events: list[ClinicalEvent]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                e.event_id,
                e.patient_id,
                e.event_type,
                e.t_start.isoformat(),
                e.t_end.isoformat(),
                e.stay_start.isoformat(),
                e.stay_end.isoformat(),
                json.dumps(e.attributes, ensure_ascii=False, default=str),
                e.confidence,
                now,
                now,
            )
            for e in events
        ]
        ref_rows = [
            (e.event_id, ref_id, relation)
            for e in events
            for ref_id, relation in e.references.items()
        ]
        with self.transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO events (
                       event_id, patient_id, event_type,
                       t_start, t_end, stay_start, stay_end,
                       attributes, confidence, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            if ref_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO event_references "
                    "(event_id, ref_id, relation) VALUES (?,?,?)",
                    ref_rows,
                )
        return len(events)

    def get(self, event_id: str) -> Optional[ClinicalEvent]:
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    def update(self, event: ClinicalEvent) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            cur = conn.execute(
                """UPDATE events SET patient_id=?, event_type=?,
                          t_start=?, t_end=?, stay_start=?, stay_end=?,
                          attributes=?, confidence=?, updated_at=?
                   WHERE event_id = ?""",
                (
                    event.patient_id,
                    event.event_type,
                    event.t_start.isoformat(),
                    event.t_end.isoformat(),
                    event.stay_start.isoformat(),
                    event.stay_end.isoformat(),
                    json.dumps(event.attributes, ensure_ascii=False, default=str),
                    event.confidence,
                    now,
                    event.event_id,
                ),
            )
            return cur.rowcount > 0

    def delete(self, event_id: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            return cur.rowcount > 0

    # ── Queries ───────────────────────────────────────────────────
    def count(self) -> int:
        assert self._conn is not None
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def all(self) -> list[ClinicalEvent]:
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY t_start"
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def find_by_patient(self, patient_id: str) -> list[ClinicalEvent]:
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE patient_id = ? ORDER BY t_start",
                (patient_id,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def find_by_type(self, event_type: str) -> list[ClinicalEvent]:
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY t_start",
                (event_type,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def find_in_window(
        self,
        patient_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ClinicalEvent]:
        """Alle Ereignisse eines Patienten, deren [t_start, t_end] das Fenster schneidet."""
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM events
                   WHERE patient_id = ?
                     AND NOT (t_end < ? OR t_start > ?)
                   ORDER BY t_start""",
                (patient_id, window_start.isoformat(), window_end.isoformat()),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def find_by_attribute(
        self, key: str, value, *, patient_id: Optional[str] = None
    ) -> list[ClinicalEvent]:
        """JSON-Extract-Suche. SQLite >= 3.38 hat ->>-Operator."""
        assert self._conn is not None
        sql = "SELECT * FROM events WHERE json_extract(attributes, ?) = ?"
        params: list = [f"$.{key}", value]
        if patient_id:
            sql += " AND patient_id = ?"
            params.append(patient_id)
        sql += " ORDER BY t_start"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def references_of(self, event_id: str) -> dict[str, str]:
        """Alle ausgehenden Referenzen eines Ereignisses.

        Returns: {ref_id: relation_string}
        """
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT ref_id, relation FROM event_references WHERE event_id = ?",
                (event_id,),
            ).fetchall()
        return {r["ref_id"]: r["relation"] for r in rows}

    def referenced_by(self, ref_id: str) -> dict[str, str]:
        """Alle Ereignisse, die ref_id referenzieren (inverse ρ).

        Returns: {event_id: relation_string}
        """
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, relation FROM event_references WHERE ref_id = ?",
                (ref_id,),
            ).fetchall()
        return {r["event_id"]: r["relation"] for r in rows}

    def find_by_relation(
        self,
        relation: str,
        *,
        event_id: Optional[str] = None,
        ref_id: Optional[str] = None,
    ) -> list[tuple[str, str]]:
        """Alle (event_id, ref_id)-Paare mit gegebener Relation.

        Optional einschränkbar auf bestimmte event_id oder ref_id.
        """
        assert self._conn is not None
        sql = "SELECT event_id, ref_id FROM event_references WHERE relation = ?"
        params: list = [relation]
        if event_id:
            sql += " AND event_id = ?"
            params.append(event_id)
        if ref_id:
            sql += " AND ref_id = ?"
            params.append(ref_id)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [(r["event_id"], r["ref_id"]) for r in rows]

    # ── Aggregate ─────────────────────────────────────────────────
    def patient_summary(self, patient_id: str) -> dict:
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) AS n,
                          MIN(t_start) AS first_event,
                          MAX(t_end) AS last_event
                   FROM events WHERE patient_id = ?""",
                (patient_id,),
            ).fetchone()
            type_rows = self._conn.execute(
                """SELECT event_type, COUNT(*) AS n
                   FROM events WHERE patient_id = ?
                   GROUP BY event_type ORDER BY n DESC""",
                (patient_id,),
            ).fetchall()
        return {
            "patient_id": patient_id,
            "event_count": row["n"] if row["n"] else 0,
            "first_event": row["first_event"],
            "last_event": row["last_event"],
            "by_type": {r["event_type"]: r["n"] for r in type_rows},
        }

    # ── Helper ────────────────────────────────────────────────────
    def _row_to_event(self, row: sqlite3.Row) -> ClinicalEvent:
        refs = self.references_of(row["event_id"])
        return ClinicalEvent(
            event_id=row["event_id"],
            patient_id=row["patient_id"],
            event_type=row["event_type"],
            t_start=datetime.fromisoformat(row["t_start"]),
            t_end=datetime.fromisoformat(row["t_end"]),
            stay_start=datetime.fromisoformat(row["stay_start"]),
            stay_end=datetime.fromisoformat(row["stay_end"]),
            attributes=json.loads(row["attributes"]) if row["attributes"] else {},
            references=refs,
            confidence=row["confidence"],
        )

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:
        return f"SQLiteEventStore(path={self.path!r}, count={self.count()})"
