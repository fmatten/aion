# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""AION Clinical — Hauptanwendung (PySide6)."""
from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QStatusBar, QFileDialog,
    QMessageBox,
)

from aion.core.types import TypeHierarchy, TypeHierarchyError
from aion.core.logging_setup import setup_logging, get_logger
from aion.core.privacy import safe_path
from aion.persistence.sqlite_store import SQLiteEventStore
from aion.gui.tabs.type_editor import TypeHierarchyTab
from aion.gui.tabs.events_tab import EventsTab
from aion.gui.tabs.allen_tab import AllenVisualizerTab
from aion.gui.tabs.causal_tab import CausalGraphTab
from aion.gui.tabs.schema_tab import SchemaEditorTab

log = get_logger(__name__)


class AIONApp(QMainWindow):
    def __init__(self, db_path: str = ":memory:"):
        super().__init__()
        self.setWindowTitle("AION Clinical — Editor")
        self.resize(1200, 780)
        self.setMinimumSize(900, 600)

        self.hierarchy = TypeHierarchy()
        self.store = SQLiteEventStore(db_path)

        self._build_menu()
        self._build_tabs()
        self._build_statusbar()
        self._refresh_status()

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        filem = menubar.addMenu("&Datei")

        act_open = QAction("Schema laden (YAML)…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._load_yaml)
        filem.addAction(act_open)

        act_save = QAction("Schema speichern…", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._save_yaml)
        filem.addAction(act_save)

        filem.addSeparator()

        act_open_db = QAction("Datenbank öffnen…", self)
        act_open_db.triggered.connect(self._open_db)
        filem.addAction(act_open_db)

        act_export_db = QAction("Datenbank exportieren…", self)
        act_export_db.triggered.connect(self._export_db)
        filem.addAction(act_export_db)

        filem.addSeparator()

        act_quit = QAction("Beenden", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        filem.addAction(act_quit)

        helpm = menubar.addMenu("&Hilfe")
        act_about = QAction("Über AION", self)
        act_about.triggered.connect(self._about)
        helpm.addAction(act_about)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()

        self.tab_types  = TypeHierarchyTab(self.hierarchy, on_change=self._refresh_status)
        self.tab_events = EventsTab(self.hierarchy, self.store)
        self.tab_allen  = AllenVisualizerTab()
        self.tab_causal = CausalGraphTab()
        self.tab_schema = SchemaEditorTab(
            get_hierarchy=lambda: self.hierarchy,
            set_hierarchy=self._set_hierarchy,
        )

        self.tabs.addTab(self.tab_types,  "Typ-Hierarchie")
        self.tabs.addTab(self.tab_events, "Ereignisse")
        self.tabs.addTab(self.tab_allen,  "Allen-Relationen")
        self.tabs.addTab(self.tab_causal, "Kausalgraph")
        self.tabs.addTab(self.tab_schema, "Schema-Editor")

        self.setCentralWidget(self.tabs)

    def _build_statusbar(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    def _refresh_status(self) -> None:
        n_types = len(self.hierarchy)
        n_events = len(self.store)
        self.status.showMessage(
            f"{n_types} Typen | {n_events} Ereignisse | DB: {self.store.path}"
        )

    def _set_hierarchy(self, h: TypeHierarchy) -> None:
        self.hierarchy = h
        self.tab_types.set_hierarchy(h)
        self.tab_events.hierarchy = h
        self._refresh_status()

    # ── Dateioperationen ──────────────────────────────────────────
    def _load_yaml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Schema laden", "", "YAML (*.yaml *.yml);;Alle Dateien (*)"
        )
        if not path:
            return
        try:
            h = TypeHierarchy.from_yaml(path)
        except FileNotFoundError:
            log.error("YAML-Datei nicht gefunden: %s", safe_path(path))
            QMessageBox.critical(
                self, "Datei nicht gefunden",
                f"Die Datei existiert nicht:\n{path}",
            )
            return
        except ImportError:
            log.error("PyYAML fehlt — Schema-Import nicht möglich")
            QMessageBox.critical(
                self, "PyYAML nicht installiert",
                "Zum Laden von YAML-Schemata wird PyYAML benötigt.\n\n"
                "Installation:  pip install PyYAML",
            )
            return
        except (TypeHierarchyError, ValueError, KeyError) as e:
            log.warning("Schema-Validierung fehlgeschlagen für %s: %s", safe_path(path), e)
            QMessageBox.critical(
                self, "Schema ungültig",
                f"Das Schema konnte nicht geladen werden:\n\n{e}\n\n"
                f"Datei: {path}",
            )
            return
        except Exception as e:
            log.exception("Unerwarteter Fehler beim Laden von %s", safe_path(path))
            QMessageBox.critical(
                self, "Unerwarteter Fehler",
                f"Beim Laden ist ein unerwarteter Fehler aufgetreten:\n\n"
                f"{type(e).__name__}: {e}\n\n"
                f"Details im Log unter ~/.aion/aion-gui.log",
            )
            return

        self._set_hierarchy(h)
        self.tab_schema.refresh()
        log.info("Schema geladen: %d Typen aus %s", len(h), safe_path(path))
        QMessageBox.information(self, "OK", f"{len(h)} Typen geladen.")

    def _save_yaml(self) -> None:
        try:
            import yaml
        except ImportError:
            QMessageBox.critical(self, "Fehler", "PyYAML nicht installiert.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Schema speichern", "", "YAML (*.yaml)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.hierarchy.to_dict(), f,
                           allow_unicode=True, sort_keys=False)
        QMessageBox.information(self, "OK", f"Schema in {path} gespeichert.")

    def _open_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Datenbank öffnen", "",
            "SQLite (*.db *.sqlite *.sqlite3);;Alle Dateien (*)"
        )
        if not path:
            return
        self.store.close()
        self.store = SQLiteEventStore(path)
        self.tab_events.store = self.store
        self.tab_events.refresh()
        self._refresh_status()

    def _export_db(self) -> None:
        import sqlite3
        path, _ = QFileDialog.getSaveFileName(
            self, "Datenbank exportieren", "", "SQLite (*.db)"
        )
        if not path:
            return
        target = sqlite3.connect(path)
        with target:
            self.store._conn.backup(target)
        target.close()
        QMessageBox.information(self, "OK", f"Datenbank gesichert: {path}")

    def _about(self) -> None:
        import aion
        QMessageBox.information(
            self, "Über AION Clinical",
            f"AION Clinical v{aion.__version__}\n\n"
            "Formale Wissensrepräsentation für klinische Verläufe.\n"
            "Implementierung der mathematischen Strukturen aus AION_v1.0:\n"
            "  • Typ-Hierarchie (DAG, mit Multi-Inheritance-Konfliktcheck)\n"
            "  • Ereignismodell mit typisierten Beziehungen ρ: E → R\n"
            "  • Allen-Algebra (13 Relationen, Fuzzy-Variante)\n"
            "  • Kausalgraph mit formaler Backdoor-Validierung\n"
            "  • TCFG (CYK, Beam Search, Pattern-Mining)\n\n"
            "Stdlib-only Kern, PySide6-GUI (LGPL-3.0).",
        )

    def closeEvent(self, event) -> None:
        try:
            self.store.close()
        except Exception:
            log.exception("Fehler beim Schließen der Datenbank")
        super().closeEvent(event)


def main() -> int:
    # Logging zuerst — damit alle nachfolgenden Aufrufe loggen können.
    # File-Logging in ~/.aion/aion-gui.log für Post-Mortem nach Vorführungen.
    log_file = setup_logging(file_logging=True)
    log.info("AION GUI startet")
    if log_file:
        log.info("Log-Datei: %s", safe_path(log_file))

    db = ":memory:"
    if len(sys.argv) > 1:
        db = sys.argv[1]
    log.info("Datenbank: %s", safe_path(db))

    app = QApplication(sys.argv)
    try:
        win = AIONApp(db_path=db)
        win.show()
        return app.exec()
    except Exception:
        log.exception("Fataler Fehler beim Starten der GUI")
        # Auf der Konsole zusätzlich, damit User es sieht
        print("FEHLER: GUI konnte nicht gestartet werden.", file=sys.stderr)
        if log_file:
            print(f"Details in {log_file}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
