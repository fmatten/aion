# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""d-Separation und formale Validierung von Backdoor-Adjustment-Sets.

Mathematische Grundlage (Pearl, 2009, Causality):

    Eine Menge Z erfüllt das **Backdoor-Kriterium** für (X, Y) gdw:
        (1) Kein Element von Z ist Nachfahre von X (descendants(X)).
        (2) Z d-trennt X und Y im Graph G_{X̄}, in dem alle ausgehenden
            Kanten von X entfernt sind.

    **d-Separation** zwischen X und Y bei gegebener Konditionierungs-Menge Z:
        Ein Pfad ist *blockiert*, wenn:
          (a) ein nicht-Collider-Knoten W ∈ Z auf dem Pfad liegt, ODER
          (b) ein Collider-Knoten W auf dem Pfad liegt, sodass weder W noch
              irgendein Nachfahre von W in Z liegt.
        X und Y sind d-separiert von Z, wenn ALLE Pfade blockiert sind.

Diese Implementierung ist stdlib-only und nutzt eine BFS-Variante des
Algorithmus von Shachter (1998) bzw. Geiger/Verma/Pearl (1990).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from aion.core.causal import CausalGraph


@dataclass
class BackdoorValidationReport:
    """Ergebnis der formalen Backdoor-Set-Prüfung."""

    valid: bool
    treatment: str
    outcome: str
    adjustment_set: set[str]
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        head = (
            f"{'✅' if self.valid else '❌'} "
            f"Z = {sorted(self.adjustment_set) or '∅'} "
            f"für {self.treatment} → {self.outcome}"
        )
        if self.violations:
            head += "\n   Verletzungen:\n   • " + "\n   • ".join(self.violations)
        return head


def d_separates(
    graph: CausalGraph,
    x: set[str],
    y: set[str],
    z: set[str],
) -> bool:
    """Prüft, ob Z die Mengen X und Y d-trennt.

    Algorithmus (Lauritzen / „moralization"):
        1. Bestimme An(X ∪ Y ∪ Z) — den Ahnen-Subgraph der relevanten Knoten.
        2. Moralisiere: für jeden Knoten verbinde alle Eltern paarweise
           (das schließt Collider-Pfade, die durch Z geöffnet wären).
        3. Konvertiere alle gerichteten Kanten in ungerichtete.
        4. Entferne alle Knoten in Z (mitsamt ihrer Kanten).
        5. X und Y sind d-separiert ⇔ es gibt keinen Pfad zwischen
           irgendeinem x ∈ X und irgendeinem y ∈ Y im Restgraphen.

    Dies ist äquivalent zur originalen d-Separation-Definition (Pearl 1988,
    Geiger/Verma/Pearl 1990) und algorithmisch einfacher als Bayes-Ball.

    Returns:
        True ⇔ alle Pfade von X nach Y sind durch Z blockiert.
    """
    if not x or not y:
        return True
    if x & y:  # direkte Überlappung
        return False

    # ── 1. Ancestral subgraph An(X ∪ Y ∪ Z) ──
    relevant = set(x) | set(y) | set(z)
    ancestral: set[str] = set(relevant)
    for node in relevant:
        ancestral |= graph.ancestors(node)

    # ── 2./3. Moralisieren + Undirected machen ──
    # adjacency: dict[node, set[neighbor]] — ungerichtet
    adj: dict[str, set[str]] = {n: set() for n in ancestral}
    for n in ancestral:
        parents_in_an = graph.parents(n) & ancestral
        # Originalkanten parent → n
        for p in parents_in_an:
            adj[p].add(n)
            adj[n].add(p)
        # Moralisierung: alle Eltern paarweise verbinden
        parents_list = list(parents_in_an)
        for i in range(len(parents_list)):
            for j in range(i + 1, len(parents_list)):
                a, b = parents_list[i], parents_list[j]
                adj[a].add(b)
                adj[b].add(a)

    # ── 4. Z entfernen ──
    for node in z:
        if node in adj:
            for neighbor in adj[node]:
                adj[neighbor].discard(node)
            del adj[node]

    # ── 5. Erreichbarkeit prüfen (BFS von jedem x ∈ X) ──
    starts = x - z
    targets = y - z
    if not starts or not targets:
        return True

    visited: set[str] = set()
    queue = deque(starts)
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if node in targets and node not in x:
            return False
        # Auch X selbst kann Y erreichen, wenn sie verbunden sind
        if node != tuple(starts)[0] and node in targets:
            return False
        for neighbor in adj.get(node, ()):
            if neighbor not in visited:
                queue.append(neighbor)

    # Letzter Check: ist irgendein y ∈ Y im visited (außer wenn es x ∈ X ist)
    return not (visited & targets - x)


def is_valid_backdoor_set(
    graph: CausalGraph,
    treatment: str,
    outcome: str,
    adjustment_set: set[str],
) -> BackdoorValidationReport:
    """Prüft formal, ob `adjustment_set` das Backdoor-Kriterium erfüllt.

    Diese Funktion liefert einen reichen Report mit konkreten Verletzungen,
    nicht nur ja/nein. Damit lässt sich debuggen, *warum* eine Menge
    nicht funktioniert.
    """
    violations: list[str] = []

    if treatment not in graph.nodes():
        violations.append(f"Treatment '{treatment}' nicht im Graph.")
    if outcome not in graph.nodes():
        violations.append(f"Outcome '{outcome}' nicht im Graph.")
    if violations:
        return BackdoorValidationReport(
            valid=False, treatment=treatment, outcome=outcome,
            adjustment_set=adjustment_set, violations=violations,
        )

    # ── Bedingung (1): Z ∩ descendants(X) = ∅ ──
    desc_x = graph.descendants(treatment)
    bad_descendants = adjustment_set & desc_x
    if bad_descendants:
        violations.append(
            f"Z enthält Nachfahren von '{treatment}': {sorted(bad_descendants)}"
        )

    # ── Bedingung (2): Z d-trennt X und Y in G_{X̄} ──
    # Konstruiere modifizierten Graphen ohne ausgehende Kanten von treatment
    g_mod = CausalGraph()
    for n in graph.nodes():
        g_mod.add_node(n)
    for src, dst in graph.edges():
        if src == treatment:
            continue  # ausgehende Kanten von X entfernen
        g_mod.add_edge(src, dst)

    if not d_separates(g_mod, {treatment}, {outcome}, adjustment_set):
        violations.append(
            f"Z d-trennt '{treatment}' und '{outcome}' nicht im "
            f"backdoor-modifizierten Graphen G_{{X̄}}."
        )

    return BackdoorValidationReport(
        valid=not violations,
        treatment=treatment,
        outcome=outcome,
        adjustment_set=adjustment_set,
        violations=violations,
    )
