# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Allen-Relationen-Visualisierer mit QSliders und QGraphicsScene (PySide6)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPen, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QGroupBox, QLabel,
    QSlider, QGraphicsScene, QGraphicsView, QTreeWidget, QTreeWidgetItem,
    QSizePolicy,
)

from aion.core.temporal import AllenInterval, FuzzyAllenInterval, ALL_RELATIONS
from aion.core.logging_setup import get_logger

log = get_logger(__name__)


class AllenVisualizerTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.sliders: dict[str, QSlider] = {}
        self.value_labels: dict[str, QLabel] = {}
        self._build()
        self._update()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        # Slider-Grid
        ctrl = QGroupBox("Intervalle")
        grid = QGridLayout(ctrl)
        defs = [
            ("I1 Start", 10),  ("I1 Ende", 40),
            ("I2 Start", 30),  ("I2 Ende", 60),
            ("I1 ε_s", 0),     ("I1 ε_e", 0),
            ("I2 ε_s", 0),     ("I2 ε_e", 0),
        ]
        # Werte in Slider-Einheiten (×10), für 0.1-Schritte zwischen 0..10
        for i, (name, init) in enumerate(defs):
            r, c = divmod(i, 2)
            grid.addWidget(QLabel(name), r, c * 3)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(init)
            slider.setMinimumWidth(180)
            slider.valueChanged.connect(self._update)
            self.sliders[name] = slider
            grid.addWidget(slider, r, c * 3 + 1)
            lbl = QLabel(f"{init / 10:.1f}")
            lbl.setMinimumWidth(40)
            self.value_labels[name] = lbl
            grid.addWidget(lbl, r, c * 3 + 2)
        layout.addWidget(ctrl)

        # Canvas (QGraphicsScene)
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setMinimumHeight(220)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout.addWidget(self.view)

        # Aktuelle Relation
        self.lbl_rel = QLabel("Relation: —")
        f = QFont(); f.setPointSize(14); f.setBold(True)
        self.lbl_rel.setFont(f)
        self.lbl_rel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_rel)

        # Konfidenztabelle
        conf_box = QGroupBox("P(I1 r I2) — Monte-Carlo (n=1000) bei ε > 0")
        conf_layout = QVBoxLayout(conf_box)
        self.conf_tree = QTreeWidget()
        self.conf_tree.setHeaderLabels(["Relation", "Wahrscheinlichkeit"])
        self.conf_tree.setColumnWidth(0, 200)
        conf_layout.addWidget(self.conf_tree)
        layout.addWidget(conf_box, 1)

    def _val(self, name: str) -> float:
        return self.sliders[name].value() / 10.0

    def _update(self) -> None:
        for name, slider in self.sliders.items():
            self.value_labels[name].setText(f"{slider.value() / 10:.1f}")

        a = self._val("I1 Start"); b = self._val("I1 Ende")
        c = self._val("I2 Start"); d = self._val("I2 Ende")
        if b < a: a, b = b, a
        if d < c: c, d = d, c

        # Canvas neu zeichnen
        self.scene.clear()
        scale = 70
        # Achse
        self.scene.addLine(20, 160, 20 + 10 * scale, 160, QPen(QColor("#999")))
        for x in range(11):
            X = 20 + x * scale
            self.scene.addLine(X, 155, X, 165, QPen(QColor("#999")))
            txt = self.scene.addText(str(x))
            txt.setDefaultTextColor(QColor("#666"))
            txt.setPos(X - 5, 165)

        # I1
        rect = self.scene.addRect(
            20 + a * scale, 50, (b - a) * scale, 40,
            QPen(QColor("#1c5fa3"), 2),
            QBrush(QColor("#4a90e2")),
        )
        txt1 = self.scene.addText(f"I1=[{a:.1f},{b:.1f}]")
        txt1.setPos(20 + a * scale, 25)

        # I2
        self.scene.addRect(
            20 + c * scale, 110, (d - c) * scale, 40,
            QPen(QColor("#a32626"), 2),
            QBrush(QColor("#e24a4a")),
        )
        txt2 = self.scene.addText(f"I2=[{c:.1f},{d:.1f}]")
        txt2.setPos(20 + c * scale, 90)

        self.scene.setSceneRect(0, 0, 20 + 10 * scale + 40, 200)

        # Allen-Relation
        try:
            i1 = AllenInterval(a, b); i2 = AllenInterval(c, d)
            rel = i1.relation_to(i2)
        except ValueError as e:
            # Kann passieren bei end < start während Slider-Drag
            log.debug("Allen-Intervall ungültig: %s", e)
            rel = "ungültig"
        self.lbl_rel.setText(f"Relation: I1 {rel} I2")

        # Fuzzy-Verteilung
        e1s = self._val("I1 ε_s"); e1e = self._val("I1 ε_e")
        e2s = self._val("I2 ε_s"); e2e = self._val("I2 ε_e")
        self.conf_tree.clear()
        if max(e1s, e1e, e2s, e2e) > 0:
            f1 = FuzzyAllenInterval(a, b, e1s, e1e)
            f2 = FuzzyAllenInterval(c, d, e2s, e2e)
            dist = f1.confidence_distribution(f2, n_samples=1000, seed=42)
            for r in ALL_RELATIONS:
                p = dist.get(r, 0.0)
                if p > 0.001:
                    item = QTreeWidgetItem([r, f"{p:.3f}"])
                    self.conf_tree.addTopLevelItem(item)
