# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""PostgreSQL-Backend für AION Clinical — Stub für 1.7.0.

ROADMAP-STATUS:
  * 1.7.0: Schnittstelle steht (dieses Modul), Implementation NICHT vorhanden
  * 1.8.0 (geplant): vollständige Implementation gegen psycopg3, mit
    Connection-Pool, Migrations, JSONB-Speicherung, Audit-Triggern in
    PL/pgSQL

Warum als Stub?
  Wir bauen Architektur sauber vor, aber nicht „auf Vorrat". Echte
  PostgreSQL-Anbindung muss gegen eine laufende Postgres-Instanz
  getestet werden — das passiert erst, wenn ein Hosting-Partner oder
  Pilot-Standort konkret PostgreSQL fordert.

Wer das hier bekommt:
    NotImplementedError mit klarer Botschaft, was als Workaround geht
    (SQLite statt PostgreSQL, oder warten auf 1.8.0).
"""
from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aion.core.events import ClinicalEvent


_NOT_IMPLEMENTED_MESSAGE = (
    "PostgreSQLEventStore ist in 1.7.0 noch nicht implementiert.\n\n"
    "Geplant für 1.8.0 mit vollständiger psycopg3-Anbindung,\n"
    "Connection-Pool, JSONB-Spalten und PL/pgSQL-Audit-Triggern.\n\n"
    "Workaround in 1.7.0: SQLite verwenden.\n"
    "  storage:\n"
    "    database: /var/lib/aion/aion.db\n"
)


class PostgreSQLEventStore:
    """Stub für PostgreSQL-Backend. Wirft NotImplementedError.

    Erfüllt strukturell das EventStore-Protocol — wer prüft
    `isinstance(store, EventStore)` bekommt True. Nutzt man eine
    Methode, kommt der NotImplementedError mit Roadmap-Hinweis.

    So funktioniert die Factory: sie kann instanziieren und die
    Anwendung kommt erst beim ersten Methoden-Aufruf in Schwierigkeiten —
    mit klarer Botschaft, statt Crash beim Import.
    """

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string

    # ── Lifecycle ────────────────────────────────────────────────
    def connect(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def close(self) -> None:
        # Idempotent — close darf auch ohne connect aufgerufen werden
        pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ── Schreiben ────────────────────────────────────────────────
    def add(self, event: "ClinicalEvent") -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def add_many(self, events: Iterable["ClinicalEvent"]) -> int:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def update(self, event: "ClinicalEvent") -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def delete(self, event_id: str) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    # ── Lesen ────────────────────────────────────────────────────
    def get(self, event_id: str) -> Optional["ClinicalEvent"]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def count(self) -> int:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def all(self) -> list["ClinicalEvent"]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def find_by_patient(self, patient_id: str) -> list["ClinicalEvent"]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def find_by_type(self, event_type: str) -> list["ClinicalEvent"]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    # ── Beziehungen ──────────────────────────────────────────────
    def references_of(self, event_id: str) -> dict[str, str]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def referenced_by(self, ref_id: str) -> dict[str, str]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)


__all__ = ["PostgreSQLEventStore"]
