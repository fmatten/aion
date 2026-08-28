# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""AION Clinical — Helfer für Jupyter Notebooks.

Diese Modul stellt drei Dinge bereit:

  1. **Rich-Display-Funktionen** für AION-Datentypen (HTML statt repr).
     Funktionieren auch ohne Jupyter — nutzen IPythons display-API
     opportunistisch.
  2. **Plotting-Wrapper** auf Basis von matplotlib (optional, ergibt
     ohne Plotting-Backend brauchbare Fehlermeldungen).
  3. **Sequence-Builder**, der Patienten-Sequenzen aus einem SQLite-
     Store extrahiert — der häufigste Workflow in einer Notebook-
     Session.

Designentscheidungen:

  * **Lazy-Import** — IPython und matplotlib werden erst beim Aufruf
    geladen. Wer notebook nicht braucht, zahlt nichts.
  * **HTML-Tabellen statt JSON-Dumps** — in Jupyter wird ein
    `to_html_table()`-Output als Tabelle gerendert, nicht als
    Code-Block.
  * **Keine Notebook-Magie** (`%load_ext` o. ä.) — bewusst dezent,
    weil Magic-Befehle den globalen Namensraum verschmutzen.

Verwendung im Notebook:

    from aion.notebook import (
        display_hierarchy, display_events,
        plot_pattern_support, plot_causal_graph,
        sequences_from_store,
    )
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from aion.core.types import TypeHierarchy
    from aion.core.events import ClinicalEvent
    from aion.core.causal import CausalGraph
    from aion.persistence.sqlite_store import SQLiteEventStore


# ────────────────────────────────────────────────────────────────────
#  Helper: IPython-Display opportunistisch
# ────────────────────────────────────────────────────────────────────
def _maybe_display_html(html: str) -> Any:
    """Versucht, HTML in einer IPython-Umgebung zu rendern.

    Wenn IPython verfügbar ist und gerade ein Notebook läuft:
    rendert die HTML-Repräsentation. Sonst: gibt den HTML-String zurück,
    damit der Aufrufer sich darum kümmern kann.
    """
    try:
        from IPython.display import display, HTML
        from IPython import get_ipython
        if get_ipython() is not None:
            display(HTML(html))
            return None
    except ImportError:
        pass
    return html


def _require_matplotlib():
    try:
        import matplotlib.pyplot as plt
        return plt
    except ImportError as e:
        raise ImportError(
            "matplotlib wird für plot_*-Funktionen benötigt.\n"
            "Installation:  pip install -e \".[notebook]\""
        ) from e


# ────────────────────────────────────────────────────────────────────
#  Display-Funktionen
# ────────────────────────────────────────────────────────────────────
def hierarchy_to_html(h: "TypeHierarchy") -> str:
    """Rendert eine TypeHierarchy als HTML-Tabelle.

    Zeigt: Typ-Name, Eltern-Liste, Attribute, Beschreibung.
    Funktioniert ohne IPython — gibt einen HTML-String zurück.
    """
    rows = []
    for name in sorted(h.all_types()):
        node = h.get(name)
        parent_set = h.parents_of(name)
        parents = ", ".join(sorted(parent_set)) if parent_set else "—"
        attrs = ", ".join(node.attributes.keys()) if node.attributes else "—"
        desc = (node.description or "")[:80]
        rows.append(
            f"<tr>"
            f"<td><code>{name}</code></td>"
            f"<td>{parents}</td>"
            f"<td>{attrs}</td>"
            f"<td>{desc}</td>"
            f"</tr>"
        )
    return (
        "<table style='border-collapse: collapse;'>"
        "<thead><tr style='border-bottom: 1px solid #ccc;'>"
        "<th style='text-align:left;padding:4px 12px;'>Typ</th>"
        "<th style='text-align:left;padding:4px 12px;'>Eltern</th>"
        "<th style='text-align:left;padding:4px 12px;'>Attribute</th>"
        "<th style='text-align:left;padding:4px 12px;'>Beschreibung</th>"
        "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def display_hierarchy(h: "TypeHierarchy") -> Any:
    """Zeigt eine TypeHierarchy als Tabelle in Jupyter."""
    return _maybe_display_html(hierarchy_to_html(h))


def events_to_html(events: list["ClinicalEvent"], max_rows: int = 50) -> str:
    """Rendert eine ClinicalEvent-Liste als HTML-Tabelle."""
    if not events:
        return "<i>Keine Ereignisse.</i>"

    truncated = events[:max_rows]
    suffix = (
        f"<p><i>…und {len(events) - max_rows} weitere</i></p>"
        if len(events) > max_rows else ""
    )

    rows = []
    for e in truncated:
        attrs_short = ", ".join(f"{k}={v}" for k, v in list(e.attributes.items())[:3])
        if len(e.attributes) > 3:
            attrs_short += f", +{len(e.attributes) - 3} more"
        rows.append(
            f"<tr>"
            f"<td><code>{e.patient_id}</code></td>"
            f"<td>{e.event_type}</td>"
            f"<td>{e.t_start.isoformat(sep=' ', timespec='minutes')}</td>"
            f"<td>{attrs_short or '—'}</td>"
            f"<td>{len(e.references)}</td>"
            f"</tr>"
        )
    return (
        f"<p><b>{len(events)} Ereignisse</b></p>"
        "<table style='border-collapse: collapse; font-size: 0.9em;'>"
        "<thead><tr style='border-bottom: 1px solid #ccc;'>"
        "<th style='text-align:left;padding:4px 12px;'>Patient</th>"
        "<th style='text-align:left;padding:4px 12px;'>Typ</th>"
        "<th style='text-align:left;padding:4px 12px;'>Zeit</th>"
        "<th style='text-align:left;padding:4px 12px;'>Attribute</th>"
        "<th style='text-align:left;padding:4px 12px;'>Refs</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + suffix
    )


def display_events(events: list["ClinicalEvent"], max_rows: int = 50) -> Any:
    """Zeigt eine Ereignis-Liste als Tabelle in Jupyter."""
    return _maybe_display_html(events_to_html(events, max_rows))


# ────────────────────────────────────────────────────────────────────
#  Plotting
# ────────────────────────────────────────────────────────────────────
def plot_pattern_support(
    patterns: dict[tuple, float],
    *,
    top: int = 15,
    title: str = "Pattern-Support",
    figsize: tuple[float, float] = (8, 6),
) -> Any:
    """Balkendiagramm: Top-N Patterns nach Support.

    Args:
        patterns: Output von TCFG.mine_patterns
        top: maximal viele Patterns anzeigen (default 15)
        title: Diagramm-Titel
        figsize: Größe (Breite, Höhe) in Inches

    Returns:
        matplotlib.figure.Figure
    """
    plt = _require_matplotlib()

    if not patterns:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "Keine Patterns gefunden", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    sorted_patterns = sorted(patterns.items(), key=lambda kv: -kv[1])[:top]
    labels = [" → ".join(p) for p, _ in sorted_patterns]
    supports = [s for _, s in sorted_patterns]

    fig, ax = plt.subplots(figsize=figsize)
    y_pos = list(range(len(labels)))
    ax.barh(y_pos, supports, color="#4a7ab8")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()  # höchster Support oben
    ax.set_xlabel("Support")
    ax.set_xlim(0, 1.0)
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


def plot_causal_graph(
    g: "CausalGraph",
    *,
    treatment: Optional[str] = None,
    outcome: Optional[str] = None,
    backdoor_set: Optional[set[str]] = None,
    figsize: tuple[float, float] = (7, 5),
    title: Optional[str] = None,
) -> Any:
    """Zeichnet einen kausalen Graphen.

    Wenn networkx verfügbar, wird Spring-Layout genutzt; sonst Kreis.

    Treatment in Blau, Outcome in Orange, Backdoor-Set in Rot,
    sonstige Knoten grau.
    """
    plt = _require_matplotlib()

    nodes = g.nodes()
    if not nodes:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "Leerer Graph", ha="center", va="center",
                transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    # Layout via networkx wenn verfügbar, sonst Kreis
    try:
        import networkx as nx
        nxg = nx.DiGraph()
        nxg.add_nodes_from(nodes)
        nxg.add_edges_from(g.edges())
        pos = nx.spring_layout(nxg, seed=42)
    except ImportError:
        import math
        pos = {
            n: (math.cos(2 * math.pi * i / len(nodes)),
                math.sin(2 * math.pi * i / len(nodes)))
            for i, n in enumerate(nodes)
        }

    # Farben
    backdoor_set = backdoor_set or set()
    colors = []
    for n in nodes:
        if n == treatment:
            colors.append("#3478d4")        # Blau
        elif n == outcome:
            colors.append("#e08020")        # Orange
        elif n in backdoor_set:
            colors.append("#d04040")        # Rot
        else:
            colors.append("#a0a0a0")        # Grau

    fig, ax = plt.subplots(figsize=figsize)

    # Kanten zeichnen (FancyArrowPatch für Pfeilspitzen)
    for src, dst in g.edges():
        x0, y0 = pos[src]
        x1, y1 = pos[dst]
        ax.annotate(
            "", xy=(x1, y1), xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", color="#888888",
                            shrinkA=15, shrinkB=15, lw=1.5),
        )

    # Knoten zeichnen
    for n, (x, y), c in zip(nodes, [pos[n] for n in nodes], colors):
        ax.scatter([x], [y], s=1500, c=[c], edgecolors="white", linewidths=2,
                   zorder=10)
        ax.text(x, y, n, ha="center", va="center", fontsize=10,
                color="white", fontweight="bold", zorder=11)

    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.set_aspect("equal")
    ax.set_axis_off()
    if title:
        ax.set_title(title)
    fig.tight_layout()
    return fig


# ────────────────────────────────────────────────────────────────────
#  Sequence-Extraction (häufigster Notebook-Workflow)
# ────────────────────────────────────────────────────────────────────
def sequences_from_store(
    store: "SQLiteEventStore",
    *,
    patient_ids: Optional[list[str]] = None,
) -> list[list[str]]:
    """Extrahiert Patientensequenzen für Pattern-Mining aus einer DB.

    Args:
        store: SQLiteEventStore (geöffnet)
        patient_ids: optional Liste; wenn None, alle Patienten

    Returns:
        Liste von Sequenzen, jeweils Event-Type-Strings, chronologisch.
    """
    all_events = store.all()
    by_patient: dict[str, list[Any]] = {}
    for e in all_events:
        if patient_ids and e.patient_id not in patient_ids:
            continue
        by_patient.setdefault(e.patient_id, []).append(e)

    sequences: list[list[str]] = []
    for pid, events in by_patient.items():
        events.sort(key=lambda x: x.t_start)
        sequences.append([e.event_type for e in events])
    return sequences


__all__ = [
    "hierarchy_to_html", "display_hierarchy",
    "events_to_html", "display_events",
    "plot_pattern_support", "plot_causal_graph",
    "sequences_from_store",
]
