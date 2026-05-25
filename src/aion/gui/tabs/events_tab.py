# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Ereignistabellen-Tab mit QTableView und SQLite-Persistenz (PySide6)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTableView, QHeaderView, QMessageBox, QDialog, QDialogButtonBox,
    QFormLayout, QComboBox,
)

from aion.core.types import TypeHierarchy
from aion.core.events import ClinicalEvent
from aion.core.logging_setup import get_logger
from aion.core.privacy import pseudonymize
from aion.persistence.sqlite_store import SQLiteEventStore

log = get_logger(__name__)


COLS = ["Patient", "Typ", "Start", "Ende", "Attribute", "Konfidenz"]


class EventTableModel(QAbstractTableModel):
    def __init__(self, events: list[ClinicalEvent] = None):
        super().__init__()
        self._events: list[ClinicalEvent] = events or []

    def set_events(self, events: list[ClinicalEvent]) -> None:
        self.beginResetModel()
        self._events = events
        self.endResetModel()

    def event_at(self, row: int) -> Optional[ClinicalEvent]:
        if 0 <= row < len(self._events):
            return self._events[row]
        return None

    # Qt-Interface ────────────────────────────────────────────────
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._events)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        e = self._events[index.row()]
        col = index.column()
        if col == 0: return e.patient_id
        if col == 1: return e.event_type
        if col == 2: return e.t_start.isoformat(timespec="minutes")
        if col == 3: return e.t_end.isoformat(timespec="minutes")
        if col == 4: return ", ".join(f"{k}={v}" for k, v in e.attributes.items())
        if col == 5: return f"{e.confidence:.2f}"
        return None


class EventsTab(QWidget):
    def __init__(
        self,
        hierarchy: TypeHierarchy,
        store: SQLiteEventStore,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.hierarchy = hierarchy
        self.store = store
        self.model = EventTableModel()
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        for label, slot in [
            ("+ Ereignis",      self._add),
            ("– Löschen",       self._delete),
            ("↻ Aktualisieren", self.refresh),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)

        toolbar.addSpacing(20)
        toolbar.addWidget(QLabel("Filter Patient:"))
        self.ed_filter = QLineEdit()
        self.ed_filter.setMaximumWidth(160)
        self.ed_filter.returnPressed.connect(self.refresh)
        toolbar.addWidget(self.ed_filter)
        btn_apply = QPushButton("Anwenden")
        btn_apply.clicked.connect(self.refresh)
        toolbar.addWidget(btn_apply)

        toolbar.addStretch()
        self.lbl_count = QLabel("")
        toolbar.addWidget(self.lbl_count)
        layout.addLayout(toolbar)

        # Tabelle
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate([80, 150, 150, 150, 320, 70]):
            self.table.setColumnWidth(i, w)
        layout.addWidget(self.table, 1)

    def refresh(self) -> None:
        patient_filter = self.ed_filter.text().strip()
        events = (
            self.store.find_by_patient(patient_filter)
            if patient_filter
            else self.store.all()
        )
        self.model.set_events(events)
        self.lbl_count.setText(f"{len(events)} Ereignisse")

    def _add(self) -> None:
        types = self.hierarchy.all_types()
        if not types:
            QMessageBox.warning(self, "Hinweis", "Erst Typ-Hierarchie befüllen.")
            return
        dlg = EventDialog(types, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self.store.add(dlg.event)
                self.refresh()
                log.info("Ereignis hinzugefügt: %s (Patient %s)",
                         dlg.event.event_type, pseudonymize(dlg.event.patient_id))
            except Exception as e:
                log.exception("Fehler beim Speichern eines Ereignisses")
                QMessageBox.critical(
                    self, "Speichern fehlgeschlagen",
                    f"Das Ereignis konnte nicht gespeichert werden:\n\n"
                    f"{type(e).__name__}: {e}",
                )

    def _delete(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        ans = QMessageBox.question(
            self, "Löschen", f"{len(rows)} Ereignis(se) löschen?"
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        for r in rows:
            ev = self.model.event_at(r)
            if ev:
                self.store.delete(ev.event_id)
        self.refresh()


class EventDialog(QDialog):
    def __init__(self, types: list[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Ereignis hinzufügen")
        self.event: Optional[ClinicalEvent] = None
        self._build(types)
        self.resize(440, 320)

    def _build(self, types: list[str]) -> None:
        layout = QFormLayout(self)
        now = datetime.utcnow().replace(microsecond=0).isoformat(timespec="minutes")

        self.ed_patient = QLineEdit("P001")
        layout.addRow("Patient-ID:", self.ed_patient)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(types)
        layout.addRow("Typ:", self.cmb_type)

        self.ed_t_start = QLineEdit(now)
        layout.addRow("Ereignis-Start (ISO):", self.ed_t_start)

        self.ed_t_end = QLineEdit(now)
        layout.addRow("Ereignis-Ende (ISO):", self.ed_t_end)

        self.ed_stay_start = QLineEdit(now)
        layout.addRow("Aufenthalt-Start (ISO):", self.ed_stay_start)

        self.ed_stay_end = QLineEdit(now)
        layout.addRow("Aufenthalt-Ende (ISO):", self.ed_stay_end)

        self.ed_conf = QLineEdit("1.0")
        layout.addRow("Konfidenz [0..1]:", self.ed_conf)

        self.ed_attrs = QLineEdit("{}")
        layout.addRow("Attribute (JSON):", self.ed_attrs)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def _save(self) -> None:
        try:
            ev = ClinicalEvent(
                patient_id=self.ed_patient.text().strip(),
                event_type=self.cmb_type.currentText(),
                t_start=datetime.fromisoformat(self.ed_t_start.text()),
                t_end=datetime.fromisoformat(self.ed_t_end.text()),
                stay_start=datetime.fromisoformat(self.ed_stay_start.text()),
                stay_end=datetime.fromisoformat(self.ed_stay_end.text()),
                attributes=json.loads(self.ed_attrs.text() or "{}"),
                confidence=float(self.ed_conf.text()),
            )
            if not ev.is_temporally_embedded():
                ans = QMessageBox.question(
                    self, "Warnung",
                    "Ereignisintervall liegt nicht innerhalb des Aufenthalts.\n"
                    "Trotzdem speichern?",
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
            self.event = ev
            self.accept()
        except ValueError as e:
            log.warning("Ereignis-Eingabe ungültig: %s", e)
            QMessageBox.critical(
                self, "Eingabe ungültig",
                f"Bitte korrigieren Sie die Eingabe:\n\n{e}",
            )
        except json.JSONDecodeError as e:
            log.warning("Ereignis-Attribute kein gültiges JSON: %s", e)
            QMessageBox.critical(
                self, "JSON ungültig",
                f"Das Attribut-Feld muss gültiges JSON sein.\n\n"
                f"Beispiel:  {{\"sofa_score\": 8, \"lactate\": 4.2}}\n\n"
                f"Fehler: {e}",
            )
        except Exception as e:
            log.exception("Unerwarteter Fehler beim Erzeugen eines Ereignisses")
            QMessageBox.critical(
                self, "Unerwarteter Fehler",
                f"{type(e).__name__}: {e}\n\nDetails im Log.",
            )
