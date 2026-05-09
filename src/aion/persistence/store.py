# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""EventStore-Protocol für AION Clinical.

Definiert die abstrakte Schnittstelle, die jeder konkrete Storage-Adapter
erfüllen muss. Heute: SQLite. Geplant: PostgreSQL.

Designentscheidung (1.7.0):

  * Protocol statt ABC. Wir wollen Strukturelle Kompatibilität, kein
    explizites Inheritance. SQLiteEventStore erfüllt das Protocol
    automatisch, ohne dass es davon erben muss — das vermeidet
    Migrations-Brüche bei Bestandscode.
  * Methoden-Signatur ist genau das, was SQLiteEventStore heute
    anbietet — damit ist 100% Rückwärts-Kompatibilität sichergestellt.
  * `create_event_store(cfg)` als Factory. Anhand des
    Database-Strings wird automatisch das richtige Backend gewählt.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable, Iterable, Iterator, Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime
    from aion.core.events import ClinicalEvent
    from aion.config import AionConfig


@runtime_checkable
class EventStore(Protocol):
    """Abstrakte Schnittstelle für AION Event-Speicher.

    Alle Storage-Backends (SQLite, PostgreSQL, …) müssen diese
    Schnittstelle erfüllen. SQLiteEventStore erfüllt sie heute schon
    strukturell. PostgreSQLEventStore wird sie ab 1.8.0 erfüllen.

    Konventionen:
        * `connect()` und `close()` müssen idempotent sein
        * `__enter__` / `__exit__` für Context-Manager-Nutzung
        * `add_many` ist atomar (alles-oder-nichts)
        * Methoden, die nichts finden, geben `None` oder leere Liste zurück,
          werfen keine Exceptions
    """

    # ── Lifecycle ────────────────────────────────────────────────
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "EventStore": ...
    def __exit__(self, *args) -> None: ...

    # ── Schreiben ────────────────────────────────────────────────
    def add(self, event: "ClinicalEvent") -> None: ...
    def add_many(self, events: Iterable["ClinicalEvent"]) -> int: ...
    def update(self, event: "ClinicalEvent") -> bool: ...
    def delete(self, event_id: str) -> bool: ...

    # ── Lesen ────────────────────────────────────────────────────
    def get(self, event_id: str) -> Optional["ClinicalEvent"]: ...
    def count(self) -> int: ...
    def all(self) -> list["ClinicalEvent"]: ...
    def find_by_patient(self, patient_id: str) -> list["ClinicalEvent"]: ...
    def find_by_type(self, event_type: str) -> list["ClinicalEvent"]: ...

    # ── Beziehungen ──────────────────────────────────────────────
    def references_of(self, event_id: str) -> dict[str, str]: ...
    def referenced_by(self, ref_id: str) -> dict[str, str]: ...


# ─────────────────────────────────────────────────────────────────
#  Factory
# ─────────────────────────────────────────────────────────────────
def create_event_store(
    cfg: Optional["AionConfig"] = None,
    *,
    database: Optional[str] = None,
) -> EventStore:
    """Erzeugt ein passendes EventStore-Backend für die Konfiguration.

    Args:
        cfg: AionConfig-Instanz. Wenn None, wird `get_config()` verwendet.
        database: optional, überschreibt den Pfad/URL aus der Config.
                  Praktisch für Tests.

    Returns:
        Ein EventStore — SQLite oder PostgreSQL, je nach URL.

    Backend-Auswahl:
        * String beginnt mit `postgresql://` → `PostgreSQLEventStore`
          (in 1.7.0 noch Stub mit NotImplementedError)
        * Sonst → `SQLiteEventStore`
    """
    if cfg is None:
        from aion.config import get_config
        cfg = get_config()

    db_url = database if database is not None else cfg.storage.database

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        from aion.persistence.postgres_store import PostgreSQLEventStore
        return PostgreSQLEventStore(db_url)

    # Default: SQLite
    from aion.persistence.sqlite_store import SQLiteEventStore
    return SQLiteEventStore(db_url)


__all__ = ["EventStore", "create_event_store"]
