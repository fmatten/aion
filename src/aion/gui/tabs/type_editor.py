# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Typ-Hierarchie-Editor mit QTreeWidget und Detail-Panel (PySide6)."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QListWidget, QTextEdit, QFormLayout, QGroupBox,
    QInputDialog, QMessageBox, QDialog, QDialogButtonBox, QComboBox, QLineEdit,
    QCheckBox, QHeaderView,
)

from aion.core.types import TypeHierarchy, TypeHierarchyError


class TypeHierarchyTab(QWidget):
    """Typ-Hierarchie-Editor."""

    changed = Signal()  # Emittiert nach jeder Änderung

    def __init__(
        self,
        hierarchy: TypeHierarchy,
        on_change: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.hierarchy = hierarchy
        if on_change:
            self.changed.connect(on_change)
        self._build()
        self.refresh()

    def set_hierarchy(self, h: TypeHierarchy) -> None:
        self.hierarchy = h
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        for label, slot in [
            ("+ Typ",       self._add_type),
            ("+ Subtyp",    self._add_subtype),
            ("+ Attribut",  self._add_attribute),
            ("– Löschen",   self._delete_type),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addSpacing(20)
        btn_validate = QPushButton("Validieren")
        btn_validate.clicked.connect(self._validate)
        toolbar.addWidget(btn_validate)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Splitter: Tree | Details
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Typ-Hierarchie", "FHIR"])
        self.tree.setColumnWidth(0, 280)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.itemSelectionChanged.connect(self._on_select)
        splitter.addWidget(self.tree)

        # Details
        det_box = QGroupBox("Details")
        det_layout = QFormLayout(det_box)
        self.lbl_name = QLabel("—")
        self.lbl_name.setStyleSheet("font-weight: bold;")
        self.lbl_parent = QLabel("—")
        self.lbl_fhir = QLabel("—")
        det_layout.addRow("Name:", self.lbl_name)
        det_layout.addRow("Parent:", self.lbl_parent)
        det_layout.addRow("FHIR:", self.lbl_fhir)

        self.lst_anc = QListWidget()
        self.lst_anc.setMaximumHeight(110)
        det_layout.addRow("Vorfahren:", self.lst_anc)

        self.lst_attrs = QListWidget()
        det_layout.addRow("Attribute:", self.lst_attrs)

        self.txt_desc = QTextEdit()
        self.txt_desc.setReadOnly(True)
        self.txt_desc.setMaximumHeight(80)
        det_layout.addRow("Beschreibung:", self.txt_desc)

        splitter.addWidget(det_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

    def refresh(self) -> None:
        self.tree.clear()
        root = self._make_item(self.hierarchy.TOP)
        self.tree.addTopLevelItem(root)
        self._insert_children(root, self.hierarchy.TOP)
        self.tree.expandAll()

    def _make_item(self, name: str) -> QTreeWidgetItem:
        node = self.hierarchy._nodes.get(name)
        fhir = node.fhir_resource if node else ""
        item = QTreeWidgetItem([name, fhir or ""])
        item.setData(0, Qt.ItemDataRole.UserRole, name)
        return item

    def _insert_children(self, parent_item: QTreeWidgetItem, parent_name: str) -> None:
        for child in sorted(self.hierarchy.children_of(parent_name)):
            child_item = self._make_item(child)
            parent_item.addChild(child_item)
            self._insert_children(child_item, child)

    def _selected_name(self) -> Optional[str]:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _on_select(self) -> None:
        name = self._selected_name()
        if not name:
            return
        node = self.hierarchy._nodes.get(name)
        if not node:
            return

        self.lbl_name.setText(name)
        self.lbl_parent.setText(node.parent or "⊤")
        self.lbl_fhir.setText(node.fhir_resource or "—")

        self.lst_anc.clear()
        for a in sorted(self.hierarchy.ancestors(name)):
            self.lst_anc.addItem(a)

        self.lst_attrs.clear()
        for k, spec in node.attributes.items():
            tail = ""
            if "type" in spec:
                tail += f" [{spec['type']}]"
            if "unit" in spec:
                tail += f" ({spec['unit']})"
            if "range" in spec:
                tail += f" {spec['range']}"
            self.lst_attrs.addItem(f"{k}{tail}")

        self.txt_desc.setPlainText(node.description or "")

    def _add_type(self) -> None:
        name, ok = QInputDialog.getText(self, "Neuer Typ", "Name:")
        if not ok or not name.strip():
            return
        try:
            self.hierarchy.add_type(name.strip())
            self.refresh()
            self.changed.emit()
        except TypeHierarchyError as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def _add_subtype(self) -> None:
        parent = self._selected_name()
        if not parent:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst einen Parent-Typ auswählen.")
            return
        name, ok = QInputDialog.getText(
            self, "Neuer Subtyp", f"Name (unter '{parent}'):"
        )
        if not ok or not name.strip():
            return
        try:
            self.hierarchy.add_type(name.strip(), parent=parent)
            self.refresh()
            self.changed.emit()
        except TypeHierarchyError as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def _add_attribute(self) -> None:
        name = self._selected_name()
        if not name or name == self.hierarchy.TOP:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst einen Typ auswählen.")
            return
        dlg = AttributeDialog(self.hierarchy, name, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._on_select()
            self.changed.emit()

    def _delete_type(self) -> None:
        name = self._selected_name()
        if not name or name == self.hierarchy.TOP:
            return
        ans = QMessageBox.question(
            self, "Löschen", f"Typ '{name}' wirklich löschen?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.hierarchy.remove_type(name)
        self.refresh()
        self.changed.emit()

    def _validate(self) -> None:
        n = len(self.hierarchy)
        max_depth = max(
            (self.hierarchy.depth(t) for t in self.hierarchy.all_types()),
            default=0,
        )
        ok = self.hierarchy.is_acyclic()
        msg = (f"{'✅' if ok else '❌'} DAG {'konsistent' if ok else 'INKONSISTENT'}\n"
               f"{n} Typen, max. Tiefe: {max_depth}")
        QMessageBox.information(self, "Validierung", msg)


class AttributeDialog(QDialog):
    """Dialog zum Hinzufügen eines Attributs."""

    TYPES = ["int", "float", "string", "bool", "enum"]

    def __init__(self, hierarchy: TypeHierarchy, type_name: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(f"Attribut für {type_name}")
        self.hierarchy = hierarchy
        self.type_name = type_name
        self._build()
        self.resize(380, 320)

    def _build(self) -> None:
        layout = QFormLayout(self)

        self.ed_name = QLineEdit()
        layout.addRow("Name:", self.ed_name)

        self.cmb_type = QComboBox()
        self.cmb_type.addItems(self.TYPES)
        self.cmb_type.setCurrentText("float")
        layout.addRow("Typ:", self.cmb_type)

        self.ed_unit = QLineEdit()
        layout.addRow("Einheit:", self.ed_unit)

        self.ed_min = QLineEdit()
        layout.addRow("Min:", self.ed_min)

        self.ed_max = QLineEdit()
        layout.addRow("Max:", self.ed_max)

        self.ed_enum = QLineEdit()
        layout.addRow("Enum-Werte (kommasep.):", self.ed_enum)

        self.chk_required = QCheckBox("Pflichtfeld")
        layout.addRow("", self.chk_required)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def _save(self) -> None:
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.critical(self, "Fehler", "Name darf nicht leer sein.")
            return
        spec: dict = {"type": self.cmb_type.currentText()}
        if self.ed_unit.text().strip():
            spec["unit"] = self.ed_unit.text().strip()
        try:
            lo = self.ed_min.text().strip()
            hi = self.ed_max.text().strip()
            if lo and hi:
                spec["range"] = [float(lo), float(hi)]
        except ValueError:
            QMessageBox.critical(self, "Fehler", "Min/Max müssen Zahlen sein.")
            return
        if self.cmb_type.currentText() == "enum":
            vals = [v.strip() for v in self.ed_enum.text().split(",") if v.strip()]
            spec["values"] = vals
        if self.chk_required.isChecked():
            spec["required"] = True

        self.hierarchy._nodes[self.type_name].attributes[name] = spec
        self.accept()
