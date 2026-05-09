# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""YAML-Schema-Editor mit Live-Validierung (PySide6)."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QPlainTextEdit,
    QMessageBox,
)

from aion.core.types import TypeHierarchy, TypeHierarchyError
from aion.core.logging_setup import get_logger

log = get_logger(__name__)


class SchemaEditorTab(QWidget):
    def __init__(
        self,
        get_hierarchy: Callable[[], TypeHierarchy],
        set_hierarchy: Callable[[TypeHierarchy], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.get_hierarchy = get_hierarchy
        self.set_hierarchy = set_hierarchy
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        for label, slot in [
            ("↻ Aus Hierarchie laden", self.refresh),
            ("✓ Validieren",           self._validate),
            ("↑ Übernehmen",           self._apply),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.lbl_status = QLabel("Bereit")
        self.lbl_status.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_status)

        self.editor = QPlainTextEdit()
        font = QFont("Courier"); font.setPointSize(10)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.editor, 1)

    def refresh(self) -> None:
        try:
            import yaml
        except ImportError:
            self._set_status("❌ PyYAML fehlt — pip install PyYAML", error=True)
            return
        h = self.get_hierarchy()
        text = yaml.safe_dump(h.to_dict(), allow_unicode=True, sort_keys=False)
        self.editor.setPlainText(text)
        self._set_status(f"✅ {len(h)} Typen geladen", error=False)

    def _validate(self) -> Optional[TypeHierarchy]:
        try:
            import yaml
        except ImportError:
            log.error("PyYAML fehlt — Schema-Validierung nicht möglich")
            self._set_status("❌ PyYAML nicht installiert (pip install PyYAML)", error=True)
            return None
        try:
            data = yaml.safe_load(self.editor.toPlainText()) or {"types": []}
        except yaml.YAMLError as e:
            log.warning("YAML-Parse-Fehler: %s", e)
            self._set_status(f"❌ YAML-Syntaxfehler: {e}", error=True)
            return None
        try:
            h = TypeHierarchy.from_dict(data)
        except (TypeHierarchyError, ValueError, KeyError) as e:
            log.warning("Schema-Validierung fehlgeschlagen: %s", e)
            self._set_status(f"❌ {e}", error=True)
            return None
        except Exception as e:
            log.exception("Unerwarteter Validierungsfehler")
            self._set_status(f"❌ {type(e).__name__}: {e}", error=True)
            return None
        self._set_status(f"✅ Gültig — {len(h)} Typen", error=False)
        return h

    def _apply(self) -> None:
        h = self._validate()
        if h is None:
            return
        ans = QMessageBox.question(
            self, "Übernehmen",
            "Aktuelle Typ-Hierarchie durch das Schema ersetzen?\n"
            "Alle bisherigen Typen werden überschrieben.",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.set_hierarchy(h)
        self._set_status(f"✅ Übernommen — {len(h)} Typen", error=False)

    def _set_status(self, text: str, error: bool) -> None:
        color = "#cc0000" if error else "#007700"
        self.lbl_status.setStyleSheet(f"color: {color};")
        self.lbl_status.setText(text)
