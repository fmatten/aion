# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Append-only Audit-Trail für AION Clinical.

Designentscheidungen für 1.5.0 (Production-Vorbereitung):

  * **Append-only**: kein UPDATE, kein DELETE. Audit-Einträge sind
    rechtsverbindlich, dürfen nicht nachträglich verändert werden.
  * **Eigene SQLite-Datei**: getrennt von der Haupt-DB, damit Audit
    auch dann erhalten bleibt, wenn jemand die Patient-DB löscht oder
    ersetzt.
  * **Pseudonymisierte Patient-IDs**: Audit-Logs müssen nachvollziehen,
    wer wann was tat — aber Patient-IDs werden über `aion.privacy`
    gehasht. Wer reidentifizieren will, braucht separates Mapping.
  * **Strukturierte Felder**: Datum, User, IP, Aktion, Resource-Typ,
    Resource-ID. Frei-Text-Notizen optional in `details`.
  * **Audit-First-Pattern**: bei kritischen Operationen wird Audit
    *vor* der Operation geschrieben, nicht danach. Falls die Operation
    crasht, bleibt der Audit-Eintrag bestehen.

DSGVO-Hintergrund:
  Art. 30 DSGVO verlangt ein Verzeichnis von Verarbeitungstätigkeiten.
  Der Audit-Trail ist *eine* Säule davon — dokumentiert WER, WANN,
  WAS getan hat. Andere Säulen (Zweckbindung, Speicherdauer,
  Rechtsgrundlage) sind organisatorisch.

Verwendung:

    from aion.audit import AuditLog, AuditAction

    audit = AuditLog("/var/lib/aion/audit.db")
    audit.record(
        action=AuditAction.READ,
        user="dr.mueller",
        ip="10.0.1.42",
        resource_type="ClinicalEvent",
        resource_id=event.event_id,
        patient_id=event.patient_id,  # wird pseudonymisiert
        details="Akteneinsicht",
    )
"""
from __future__ import annotations

import enum
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Iterator, Union

from aion.core.logging_setup import get_logger
from aion.core.privacy import pseudonymize, safe_path

log = get_logger(__name__)


class AuditAction(enum.Enum):
    """Standardisiertes Vokabular für Audit-Aktionen.

    Eigene Aktionen können als String übergeben werden, aber für
    häufige Fälle gibt es vordefinierte Werte.
    """
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    IMPORT = "import"
    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"
    QUERY = "query"
    PATTERN_MINING = "pattern_mining"
    CAUSAL_ANALYSIS = "causal_analysis"


_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    action        TEXT NOT NULL,
    user          TEXT,
    ip            TEXT,
    resource_type TEXT,
    resource_id   TEXT,
    patient_hash  TEXT,
    success       INTEGER NOT NULL DEFAULT 1,
    details       TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user      ON audit_log(user);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_patient   ON audit_log(patient_hash);
CREATE INDEX IF NOT EXISTS idx_audit_resource  ON audit_log(resource_type, resource_id);
"""


# Trigger zum Verbieten von UPDATE und DELETE — append-only
_AUDIT_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log ist append-only — UPDATE verboten');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log ist append-only — DELETE verboten');
END;
"""


class AuditLog:
    """Append-only-Logger für klinische Datenzugriffe.

    Thread-safe. Einzelne Verbindung wird über RLock geteilt.
    """

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self.connect()

    def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(
            self.path, check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_AUDIT_SCHEMA)
        try:
            self._conn.executescript(_AUDIT_TRIGGERS)
        except sqlite3.OperationalError:
            # Trigger existieren bereits, ignorieren
            pass
        self._conn.commit()
        log.debug("AuditLog initialisiert: %s", safe_path(self.path))

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                log.exception("Fehler beim Schließen von AuditLog")
            self._conn = None

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Schreiben ────────────────────────────────────────────────
    def record(
        self,
        action: Union[AuditAction, str],
        *,
        user: Optional[str] = None,
        ip: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        success: bool = True,
        details: Optional[str] = None,
    ) -> int:
        """Schreibt einen Audit-Eintrag. Liefert die Audit-ID.

        Args:
            action: Aktion (AuditAction-Enum oder freier String).
            user: Benutzername / Kennung. Bei System-Aktionen z. B. "system".
            ip: IP-Adresse des Aufrufers.
            resource_type: z. B. "ClinicalEvent", "TypeHierarchy".
            resource_id: ID der betroffenen Resource.
            patient_id: WIRD PSEUDONYMISIERT, nie im Klartext gespeichert.
            success: False bei Fehlversuchen (z. B. fehlgeschlagene Auth).
            details: optionaler Freitext (z. B. Kontext der Operation).

        Returns:
            Audit-ID des neu angelegten Eintrags.
        """
        action_str = action.value if isinstance(action, AuditAction) else str(action)
        timestamp = datetime.now(timezone.utc).isoformat()
        patient_hash = pseudonymize(patient_id) if patient_id else None

        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                """INSERT INTO audit_log
                   (timestamp, action, user, ip, resource_type, resource_id,
                    patient_hash, success, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, action_str, user, ip, resource_type,
                 resource_id, patient_hash, 1 if success else 0, details),
            )
            self._conn.commit()
            return cur.lastrowid

    # ── Lesen ────────────────────────────────────────────────────
    def query(
        self,
        *,
        action: Optional[str] = None,
        user: Optional[str] = None,
        patient_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        success: Optional[bool] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Liest Audit-Einträge mit Filtern.

        Args:
            action: optional, Filter auf Aktion.
            user: optional, Filter auf User.
            patient_id: WIRD PSEUDONYMISIERT vor der Suche, damit man
                        mit dem Klartext-ID nachschauen kann.
            since/until: Zeitfenster.
            success: optional, nur erfolgreiche oder nur fehlgeschlagene.
            limit: max. Anzahl Einträge (default 1000).

        Returns:
            Liste von Dicts mit den Spalten der audit_log-Tabelle.
        """
        clauses = []
        params: list = []
        if action is not None:
            clauses.append("action = ?"); params.append(action)
        if user is not None:
            clauses.append("user = ?"); params.append(user)
        if patient_id is not None:
            clauses.append("patient_hash = ?"); params.append(pseudonymize(patient_id))
        if since is not None:
            clauses.append("timestamp >= ?"); params.append(since.isoformat())
        if until is not None:
            clauses.append("timestamp <= ?"); params.append(until.isoformat())
        if success is not None:
            clauses.append("success = ?"); params.append(1 if success else 0)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM audit_log {where} ORDER BY audit_id DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def count(self) -> int:
        """Anzahl Audit-Einträge insgesamt."""
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("SELECT COUNT(*) FROM audit_log")
            return cur.fetchone()[0]

    def export_csv(self, path: Union[str, Path]) -> int:
        """Exportiert alle Audit-Einträge als CSV. Liefert Anzahl Zeilen."""
        import csv
        path = Path(path)
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("SELECT * FROM audit_log ORDER BY audit_id")
            rows = cur.fetchall()
        if not rows:
            path.write_text("", encoding="utf-8")
            return 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(list(row))
        return len(rows)


__all__ = ["AuditAction", "AuditLog"]
