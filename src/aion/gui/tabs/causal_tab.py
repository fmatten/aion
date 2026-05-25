# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Causal-Graph-Visualizer als interaktiver QGraphicsScene-Editor (PySide6).

Funktionen:
    * Doppelklick auf leeren Canvas → neuer Knoten
    * Drag auf Knoten → verschieben (nativ via ItemIsMovable)
    * Shift+Klick auf zwei Knoten → gerichtete Kante
    * Rechtsklick auf Knoten/Kante → Kontextmenü mit Löschen
    * Treatment/Outcome rechts auswählen
    * Backdoor-Adjustment-Set wird rot eingefärbt, Nachfahren grau
"""
from __future__ import annotations

import json
import math
from typing import Optional

from PySide6.QtCore import Qt, QPointF, QRectF, QLineF, Signal
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPolygonF, QFont, QAction, QTransform,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel,
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsSimpleTextItem, QInputDialog, QMessageBox, QFileDialog,
    QGroupBox, QFormLayout, QComboBox, QListWidget, QApplication, QMenu,
)

from aion.core.causal import CausalGraph, CausalGraphError
from aion.core.logging_setup import get_logger
from aion.core.privacy import safe_path

log = get_logger(__name__)


NODE_RADIUS = 28
COLOR_DEFAULT     = QColor("#dddddd")
COLOR_TREATMENT   = QColor("#4a90e2")  # blau
COLOR_OUTCOME     = QColor("#e2904a")  # orange
COLOR_BACKDOOR    = QColor("#e24a4a")  # rot
COLOR_DESCENDANT  = QColor("#cccccc")
COLOR_EDGE        = QColor("#444444")
COLOR_EDGE_BACKDOOR = QColor("#cc3333")
COLOR_NODE_OUTLINE = QColor("#222222")
COLOR_EDGE_START  = QColor("#00aa00")


# ─── Items ────────────────────────────────────────────────────────────
class NodeItem(QGraphicsEllipseItem):
    """Knoten als Kreis. Der Name wird zentriert als Child-Label gerendert."""

    def __init__(self, name: str, x: float, y: float):
        super().__init__(-NODE_RADIUS, -NODE_RADIUS, 2 * NODE_RADIUS, 2 * NODE_RADIUS)
        self.name = name
        self.setPos(x, y)
        self.setBrush(QBrush(COLOR_DEFAULT))
        self.setPen(QPen(COLOR_NODE_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)

        font = QFont(); font.setBold(True); font.setPointSize(10)
        self.label = QGraphicsSimpleTextItem(name, self)
        self.label.setFont(font)
        self._center_label()

        self.edges: list[EdgeItem] = []  # rückbezüge für Live-Update

    def _center_label(self) -> None:
        rect = self.label.boundingRect()
        self.label.setPos(-rect.width() / 2, -rect.height() / 2)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges:
                edge.refresh()
        return super().itemChange(change, value)


class EdgeItem(QGraphicsItem):
    """Gerichtete Kante mit Pfeilspitze, gekürzt auf Knotenränder."""

    def __init__(self, src: NodeItem, dst: NodeItem):
        super().__init__()
        self.src = src; self.dst = dst
        self.color = COLOR_EDGE
        self.thick = 2
        self.setZValue(0)
        src.edges.append(self); dst.edges.append(self)

    def boundingRect(self) -> QRectF:
        p1 = self.src.pos(); p2 = self.dst.pos()
        x = min(p1.x(), p2.x()) - 10
        y = min(p1.y(), p2.y()) - 10
        w = abs(p2.x() - p1.x()) + 20
        h = abs(p2.y() - p1.y()) + 20
        return QRectF(x, y, w, h)

    def refresh(self) -> None:
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        p1 = self.src.pos(); p2 = self.dst.pos()
        line = QLineF(p1, p2)
        if line.length() < 1:
            return
        # Punkte am Knotenrand
        unit = QPointF(line.dx() / line.length(), line.dy() / line.length())
        s_edge = QPointF(p1.x() + unit.x() * NODE_RADIUS, p1.y() + unit.y() * NODE_RADIUS)
        d_edge = QPointF(p2.x() - unit.x() * NODE_RADIUS, p2.y() - unit.y() * NODE_RADIUS)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.color, self.thick))
        painter.drawLine(s_edge, d_edge)

        # Pfeilspitze
        angle = math.atan2(line.dy(), line.dx())
        arrow_len = 10
        arrow_ang = math.radians(25)
        p_arr1 = QPointF(
            d_edge.x() - arrow_len * math.cos(angle - arrow_ang),
            d_edge.y() - arrow_len * math.sin(angle - arrow_ang),
        )
        p_arr2 = QPointF(
            d_edge.x() - arrow_len * math.cos(angle + arrow_ang),
            d_edge.y() - arrow_len * math.sin(angle + arrow_ang),
        )
        painter.setBrush(QBrush(self.color))
        painter.drawPolygon(QPolygonF([d_edge, p_arr1, p_arr2]))


# ─── Scene ────────────────────────────────────────────────────────────
class GraphScene(QGraphicsScene):
    """Scene mit Doppelklick-zum-Erstellen und Shift-Klick-für-Kanten."""

    nodeAddRequested = Signal(QPointF)
    edgeRequested = Signal(str, str)
    deleteRequested = Signal(str)        # node name
    deleteEdgeRequested = Signal(str, str)  # src, dst

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, 900, 600)
        self._edge_start: Optional[NodeItem] = None

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), QTransform())
        # Falls Klick auf Label (child of node), gehe hoch
        if isinstance(item, QGraphicsSimpleTextItem):
            item = item.parentItem()
        if item is None:
            self.nodeAddRequested.emit(event.scenePos())
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), QTransform())
        if isinstance(item, QGraphicsSimpleTextItem):
            item = item.parentItem()

        # Shift+Klick: Kantenmodus
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if isinstance(item, NodeItem):
                if self._edge_start is None:
                    self._edge_start = item
                    item.setPen(QPen(COLOR_EDGE_START, 4))
                else:
                    src, dst = self._edge_start, item
                    # Highlight zurücknehmen
                    self._edge_start.setPen(QPen(COLOR_NODE_OUTLINE, 2))
                    self._edge_start = None
                    if src is not dst:
                        self.edgeRequested.emit(src.name, dst.name)
                event.accept()
                return

        # Rechtsklick: Kontextmenü
        if event.button() == Qt.MouseButton.RightButton:
            if isinstance(item, NodeItem):
                self._show_node_menu(event.screenPos(), item.name)
                event.accept()
                return
            edge = self._edge_at(event.scenePos())
            if edge is not None:
                self._show_edge_menu(event.screenPos(), edge.src.name, edge.dst.name)
                event.accept()
                return

        super().mousePressEvent(event)

    def _edge_at(self, pos: QPointF, threshold: float = 6.0) -> Optional[EdgeItem]:
        for it in self.items():
            if not isinstance(it, EdgeItem):
                continue
            p1 = it.src.pos(); p2 = it.dst.pos()
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            length_sq = dx * dx + dy * dy
            if length_sq < 1:
                continue
            t = max(0.0, min(1.0,
                ((pos.x() - p1.x()) * dx + (pos.y() - p1.y()) * dy) / length_sq))
            px, py = p1.x() + t * dx, p1.y() + t * dy
            if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 < threshold ** 2:
                return it
        return None

    def _show_node_menu(self, screen_pos, node_name: str) -> None:
        menu = QMenu()
        act_del = QAction(f"Knoten '{node_name}' löschen", menu)
        act_del.triggered.connect(lambda: self.deleteRequested.emit(node_name))
        menu.addAction(act_del)
        menu.exec(screen_pos)

    def _show_edge_menu(self, screen_pos, src: str, dst: str) -> None:
        menu = QMenu()
        act_del = QAction(f"Kante {src} → {dst} löschen", menu)
        act_del.triggered.connect(lambda: self.deleteEdgeRequested.emit(src, dst))
        menu.addAction(act_del)
        menu.exec(screen_pos)


# ─── Tab ──────────────────────────────────────────────────────────────
class CausalGraphTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.graph = CausalGraph()
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: dict[tuple[str, str], EdgeItem] = {}
        self._build()

    # ── Layout ────────────────────────────────────────────────────
    def _build(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        for label, slot in [
            ("+ Knoten",        self._add_node_dlg),
            ("🗑 Alles löschen", self._clear),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addSpacing(20)
        for label, slot in [
            ("Beispiel laden",   self._load_example),
            ("JSON exportieren", self._export),
            ("JSON importieren", self._import),
            ("DOT kopieren",     self._copy_dot),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        hint = QLabel(
            "Doppelklick: neuer Knoten   |   Drag: verschieben   |   "
            "Shift+Klick auf 2 Knoten: Kante   |   Rechtsklick: Kontextmenü"
        )
        hint.setStyleSheet("color: #555;")
        layout.addWidget(hint)

        # Splitter: Canvas | Sidepanel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        # Scene + View
        self.scene = GraphScene(self)
        self.scene.nodeAddRequested.connect(self._on_node_add_requested)
        self.scene.edgeRequested.connect(self._on_edge_requested)
        self.scene.deleteRequested.connect(self._on_delete_node)
        self.scene.deleteEdgeRequested.connect(self._on_delete_edge)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setMinimumWidth(640)
        splitter.addWidget(self.view)

        # Sidepanel
        side = QWidget()
        self._build_sidepanel(side)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

    def _build_sidepanel(self, container: QWidget) -> None:
        v = QVBoxLayout(container)

        sel = QGroupBox("Backdoor-Adjustierung")
        form = QFormLayout(sel)
        self.cmb_treatment = QComboBox()
        self.cmb_treatment.currentIndexChanged.connect(self._redraw_colors)
        form.addRow("Treatment X:", self.cmb_treatment)
        self.cmb_outcome = QComboBox()
        self.cmb_outcome.currentIndexChanged.connect(self._redraw_colors)
        form.addRow("Outcome Y:", self.cmb_outcome)
        v.addWidget(sel)

        info = QGroupBox("Adjustment-Set Z")
        info_v = QVBoxLayout(info)
        self.lst_z = QListWidget()
        self.lst_z.setMaximumHeight(110)
        info_v.addWidget(self.lst_z)
        self.lbl_paths = QLabel("Backdoor-Pfade: —")
        info_v.addWidget(self.lbl_paths)
        v.addWidget(info)

        stats = QGroupBox("Graph-Statistik")
        stats_v = QVBoxLayout(stats)
        self.lbl_stats = QLabel("—")
        stats_v.addWidget(self.lbl_stats)
        v.addWidget(stats)

        infer = QGroupBox("Demo-Inferenz P(Y=1 | do(X=1))")
        infer_v = QVBoxLayout(infer)
        infer_v.addWidget(QLabel(
            "Mit synthetischen, uniformen P-Werten\nfür alle Variablen ∈ {0, 1}."
        ))
        btn = QPushButton("Berechnen (exakt)")
        btn.clicked.connect(self._demo_inference)
        infer_v.addWidget(btn)
        self.lbl_inference = QLabel("—")
        f = QFont(); f.setPointSize(11); f.setBold(True)
        self.lbl_inference.setFont(f)
        infer_v.addWidget(self.lbl_inference)
        v.addWidget(infer)

        v.addStretch()

    # ── Scene-Events ──────────────────────────────────────────────
    def _on_node_add_requested(self, pos: QPointF) -> None:
        name, ok = QInputDialog.getText(self, "Neuer Knoten", "Variablenname:")
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            self.graph.add_node(name)
            item = NodeItem(name, pos.x(), pos.y())
            self.scene.addItem(item)
            self.node_items[name] = item
            self._refresh_combos()
            self._redraw_colors()
        except CausalGraphError as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def _on_edge_requested(self, src: str, dst: str) -> None:
        try:
            self.graph.add_edge(src, dst)
        except CausalGraphError as e:
            QMessageBox.critical(self, "Fehler", str(e))
            return
        edge = EdgeItem(self.node_items[src], self.node_items[dst])
        self.scene.addItem(edge)
        self.edge_items[(src, dst)] = edge
        self._redraw_colors()

    def _on_delete_node(self, name: str) -> None:
        ans = QMessageBox.question(self, "Löschen", f"Knoten '{name}' löschen?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        # Alle anliegenden Kanten entfernen
        for key in list(self.edge_items.keys()):
            if name in key:
                self._remove_edge_visual(*key)
        self.graph.remove_node(name)
        if name in self.node_items:
            self.scene.removeItem(self.node_items[name])
            del self.node_items[name]
        self._refresh_combos()
        self._redraw_colors()

    def _on_delete_edge(self, src: str, dst: str) -> None:
        ans = QMessageBox.question(
            self, "Löschen", f"Kante {src} → {dst} löschen?"
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.graph.remove_edge(src, dst)
        self._remove_edge_visual(src, dst)
        self._redraw_colors()

    def _remove_edge_visual(self, src: str, dst: str) -> None:
        edge = self.edge_items.pop((src, dst), None)
        if edge:
            # aus den Knoten-Listen entfernen
            for n in (edge.src, edge.dst):
                if edge in n.edges:
                    n.edges.remove(edge)
            self.scene.removeItem(edge)

    # ── Toolbar-Aktionen ──────────────────────────────────────────
    def _add_node_dlg(self) -> None:
        name, ok = QInputDialog.getText(self, "Neuer Knoten", "Variablenname:")
        if not ok or not name.strip():
            return
        name = name.strip()
        try:
            self.graph.add_node(name)
            # Mittig
            r = self.scene.sceneRect()
            item = NodeItem(name, r.center().x(), r.center().y())
            self.scene.addItem(item)
            self.node_items[name] = item
            self._refresh_combos()
            self._redraw_colors()
        except CausalGraphError as e:
            QMessageBox.critical(self, "Fehler", str(e))

    def _clear(self) -> None:
        if not self.graph.nodes():
            return
        ans = QMessageBox.question(
            self, "Alles löschen", "Den gesamten Graphen verwerfen?"
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self.graph = CausalGraph()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self._refresh_combos()

    def _load_example(self) -> None:
        """Klassisches Konfounder-Beispiel."""
        self._clear_silent()
        edges = [
            ("Z1", "X"), ("Z1", "Y"),
            ("Z2", "X"), ("Z2", "Y"),
            ("X", "Y"),
            ("X", "M"), ("M", "Y"),  # Mediator
        ]
        positions = {
            "Z1": (180, 120), "Z2": (180, 280),
            "X":  (380, 220), "M":  (520, 320),
            "Y":  (660, 220),
        }
        # Knoten erst, damit Edge-Erzeugung sie findet
        for name in {n for e in edges for n in e}:
            self.graph.add_node(name)
            x, y = positions[name]
            item = NodeItem(name, x, y)
            self.scene.addItem(item)
            self.node_items[name] = item
        for src, dst in edges:
            self.graph.add_edge(src, dst)
            edge = EdgeItem(self.node_items[src], self.node_items[dst])
            self.scene.addItem(edge)
            self.edge_items[(src, dst)] = edge

        self._refresh_combos()
        self.cmb_treatment.setCurrentText("X")
        self.cmb_outcome.setCurrentText("Y")
        self._redraw_colors()

    def _clear_silent(self) -> None:
        self.graph = CausalGraph()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "JSON exportieren", "", "JSON (*.json)"
        )
        if not path:
            return
        data = {
            "graph": self.graph.to_dict(),
            "positions": {
                n: [item.pos().x(), item.pos().y()]
                for n, item in self.node_items.items()
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "JSON importieren", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._clear_silent()
            self.graph = CausalGraph.from_dict(data["graph"])
            positions = data.get("positions", {})
            r = self.scene.sceneRect()
            import random as _rnd
            for n in self.graph.nodes():
                if n in positions:
                    x, y = positions[n]
                else:
                    x = _rnd.uniform(80, r.width() - 80)
                    y = _rnd.uniform(80, r.height() - 80)
                item = NodeItem(n, x, y)
                self.scene.addItem(item)
                self.node_items[n] = item
            for src, dst in self.graph.edges():
                edge = EdgeItem(self.node_items[src], self.node_items[dst])
                self.scene.addItem(edge)
                self.edge_items[(src, dst)] = edge
            self._refresh_combos()
            self._redraw_colors()
            log.info("Kausalgraph aus %s geladen (%d Knoten, %d Kanten)",
                     safe_path(path), len(self.graph.nodes()), len(self.graph.edges()))
        except FileNotFoundError:
            log.error("Datei nicht gefunden: %s", safe_path(path))
            QMessageBox.critical(
                self, "Datei nicht gefunden",
                f"Die Datei existiert nicht:\n{path}",
            )
        except json.JSONDecodeError as e:
            log.warning("JSON-Parse-Fehler in %s: %s", safe_path(path), e)
            QMessageBox.critical(
                self, "JSON-Fehler",
                f"Die Datei ist kein gültiges JSON:\n\n{e}\n\n"
                f"Datei: {path}",
            )
        except KeyError as e:
            log.warning("Erwartetes Feld fehlt in %s: %s", safe_path(path), e)
            QMessageBox.critical(
                self, "Format ungültig",
                f"Im JSON fehlt das erforderliche Feld {e}.\n\n"
                f"Erwartet wird ein Objekt mit den Schlüsseln 'graph' "
                f"und optional 'positions'.",
            )
        except CausalGraphError as e:
            log.warning("Graph-Validierung fehlgeschlagen: %s", e)
            QMessageBox.critical(
                self, "Graph ungültig",
                f"Der Graph ist nicht wohlgeformt:\n\n{e}",
            )
        except Exception as e:
            log.exception("Unerwarteter Fehler beim Import von %s", safe_path(path))
            QMessageBox.critical(
                self, "Unerwarteter Fehler",
                f"{type(e).__name__}: {e}\n\nDetails im Log.",
            )

    def _copy_dot(self) -> None:
        QApplication.clipboard().setText(self.graph.to_dot())
        QMessageBox.information(
            self, "DOT", "Graphviz-DOT wurde in die Zwischenablage kopiert."
        )

    def _demo_inference(self) -> None:
        treatment = self.cmb_treatment.currentText()
        outcome = self.cmb_outcome.currentText()
        if not treatment or not outcome:
            QMessageBox.warning(self, "Hinweis", "Bitte Treatment und Outcome wählen.")
            return
        try:
            bs = self.graph.find_backdoor_adjustment_set(treatment, outcome) or set()
            value_space = {z: ["0", "1"] for z in bs}

            def p_y_given_x_z(x: str, y: str, z: dict) -> float:
                lin = 0.5 * int(x) + 0.3 * sum(int(v) for v in z.values())
                p1 = 1 / (1 + math.exp(-lin))
                return p1 if y == "1" else 1 - p1

            def p_z(z: dict) -> float:
                return 0.5 ** len(z) if z else 1.0

            p = self.graph.do_backdoor(
                p_y_given_x_z, p_z, value_space,
                treatment=treatment, outcome=outcome,
                x="1", y="1",
            )
            self.lbl_inference.setText(f"P(Y=1 | do(X=1)) ≈ {p:.4f}")
            log.info("Demo-Inferenz: P(Y=1|do(X=1)) ≈ %.4f (Z=%s)",
                     p, sorted(bs))
        except CausalGraphError as e:
            log.warning("Demo-Inferenz: ungültiger Graph für %s → %s: %s",
                        treatment, outcome, e)
            QMessageBox.critical(
                self, "Graph ungültig",
                f"Inferenz nicht möglich:\n\n{e}",
            )
        except Exception as e:
            log.exception("Unerwarteter Fehler bei Demo-Inferenz")
            QMessageBox.critical(
                self, "Unerwarteter Fehler",
                f"{type(e).__name__}: {e}",
            )

    # ── Combos und Coloring ──────────────────────────────────────
    def _refresh_combos(self) -> None:
        nodes = sorted(self.graph.nodes())

        for cmb in (self.cmb_treatment, self.cmb_outcome):
            current = cmb.currentText()
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem("")
            cmb.addItems(nodes)
            if current in nodes:
                cmb.setCurrentText(current)
            cmb.blockSignals(False)

    def _redraw_colors(self) -> None:
        treatment = self.cmb_treatment.currentText() or None
        outcome = self.cmb_outcome.currentText() or None

        backdoor_set: set[str] = set()
        descendants_t: set[str] = set()
        if (treatment and outcome
                and treatment in self.graph.nodes()
                and outcome in self.graph.nodes()):
            try:
                bs = self.graph.find_backdoor_adjustment_set(treatment, outcome)
                if bs is not None:
                    backdoor_set = bs
                descendants_t = self.graph.descendants(treatment) - {outcome}
            except Exception:
                # Im Hot-Path beim Redraw — kein User-Dialog, nur Trace fürs Log
                log.debug("Backdoor-Berechnung fehlgeschlagen", exc_info=True)

        # Knoten einfärben
        for name, item in self.node_items.items():
            color = COLOR_DEFAULT
            if name == treatment:   color = COLOR_TREATMENT
            elif name == outcome:   color = COLOR_OUTCOME
            elif name in backdoor_set: color = COLOR_BACKDOOR
            elif name in descendants_t: color = COLOR_DESCENDANT
            item.setBrush(QBrush(color))

        # Kanten einfärben (Backdoor-Eingang in treatment markieren)
        for (src, dst), edge in self.edge_items.items():
            if treatment and dst == treatment:
                edge.color = COLOR_EDGE_BACKDOOR
                edge.thick = 3
            else:
                edge.color = COLOR_EDGE
                edge.thick = 2
            edge.refresh()

        # Sidepanel
        self.lst_z.clear()
        for z in sorted(backdoor_set):
            self.lst_z.addItem(z)

        n_paths = 0
        if (treatment and outcome
                and treatment in self.graph.nodes()
                and outcome in self.graph.nodes()):
            try:
                n_paths = len(self.graph.backdoor_paths(treatment, outcome))
            except Exception:
                log.debug("Backdoor-Pfade-Berechnung fehlgeschlagen", exc_info=True)
                n_paths = 0
        self.lbl_paths.setText(f"Backdoor-Pfade: {n_paths}")

        self.lbl_stats.setText(
            f"Knoten: {len(self.graph.nodes())}\n"
            f"Kanten: {len(self.graph.edges())}\n"
            f"Treatment: {treatment or '—'}\n"
            f"Outcome:   {outcome or '—'}\n"
            f"|Z|:       {len(backdoor_set)}"
        )
