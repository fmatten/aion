# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Kausaler Graph mit do-Operator und Backdoor-Adjustierung.

Mathematisches Modell:
    Kausaler Graph G = (V, E) gerichtet, azyklisch.
    do(X = x): Intervention durch Entfernen aller Kanten in X.
    Backdoor-Adjustierung:

        P(Y = y | do(X = x)) = Σ_z P(Y = y | X = x, Z = z) · P(Z = z)

    wobei Z eine gültige Backdoor-Adjustment-Menge ist.

Implementierung: stdlib-only. DoWhy/CausalML nur als optionale Plugins.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable, Optional


class CausalGraphError(Exception):
    pass


class CausalGraph:
    """Gerichteter azyklischer Graph für kausale Inferenz.

    Repräsentation: Adjazenzliste parents[v] = {u | u → v}.
    """

    def __init__(self) -> None:
        self._parents: dict[str, set[str]] = {}
        self._children: dict[str, set[str]] = {}

    # ── Mutation ──────────────────────────────────────────────────
    def add_node(self, name: str) -> None:
        if name in self._parents:
            return
        self._parents[name] = set()
        self._children[name] = set()

    def add_edge(self, src: str, dst: str) -> None:
        """Fügt gerichtete Kante src → dst hinzu. Eager-Zykluscheck."""
        self.add_node(src)
        self.add_node(dst)
        if src == dst:
            raise CausalGraphError("Selbstkante nicht erlaubt.")
        if self._reachable(dst, src):
            raise CausalGraphError(f"Kante {src}→{dst} würde Zyklus erzeugen.")
        self._parents[dst].add(src)
        self._children[src].add(dst)

    def remove_edge(self, src: str, dst: str) -> None:
        self._parents.get(dst, set()).discard(src)
        self._children.get(src, set()).discard(dst)

    def remove_node(self, name: str) -> None:
        if name not in self._parents:
            return
        for c in list(self._children[name]):
            self.remove_edge(name, c)
        for p in list(self._parents[name]):
            self.remove_edge(p, name)
        del self._parents[name]
        del self._children[name]

    # ── Queries ───────────────────────────────────────────────────
    def nodes(self) -> list[str]:
        return list(self._parents.keys())

    def edges(self) -> list[tuple[str, str]]:
        return [(p, c) for c, ps in self._parents.items() for p in ps]

    def parents(self, v: str) -> set[str]:
        return set(self._parents.get(v, set()))

    def children(self, v: str) -> set[str]:
        return set(self._children.get(v, set()))

    def ancestors(self, v: str) -> set[str]:
        """Alle Vorfahren (transitive Hülle nach oben)."""
        seen: set[str] = set()
        stack = list(self._parents.get(v, set()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self._parents.get(n, set()))
        return seen

    def descendants(self, v: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self._children.get(v, set()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self._children.get(n, set()))
        return seen

    def _reachable(self, src: str, dst: str) -> bool:
        if src == dst:
            return True
        if src not in self._parents:
            return False
        return dst in self.descendants(src)

    def topological_order(self) -> list[str]:
        """Kahn-Algorithmus."""
        in_deg = {v: len(self._parents[v]) for v in self._parents}
        queue = deque([v for v, d in in_deg.items() if d == 0])
        out: list[str] = []
        while queue:
            v = queue.popleft()
            out.append(v)
            for c in self._children[v]:
                in_deg[c] -= 1
                if in_deg[c] == 0:
                    queue.append(c)
        if len(out) != len(self._parents):
            raise CausalGraphError("Graph hat Zyklen.")
        return out

    # ── Backdoor-Kriterium ────────────────────────────────────────
    def backdoor_paths(self, treatment: str, outcome: str) -> list[list[str]]:
        """Findet alle Backdoor-Pfade von treatment nach outcome.

        Ein Backdoor-Pfad ist ein ungerichteter Pfad, der mit einem
        eingehenden Pfeil in `treatment` beginnt und in `outcome` endet.
        """
        paths: list[list[str]] = []

        def dfs(node: str, target: str, path: list[str], came_from_child: bool) -> None:
            if node == target and len(path) > 1:
                # Erste Kante musste in treatment hinein gehen (came_from=parent of treatment)
                paths.append(list(path))
                return
            # Weitergehen: gehen zu Parents (Pfeile rückwärts) und Children (Pfeile vorwärts)
            for p in self._parents.get(node, set()):
                if p in path:
                    continue
                path.append(p)
                dfs(p, target, path, came_from_child=False)
                path.pop()
            for c in self._children.get(node, set()):
                if c in path:
                    continue
                path.append(c)
                dfs(c, target, path, came_from_child=True)
                path.pop()

        # Startbedingung: erste Kante muss in treatment HINEIN gehen
        for p in self._parents.get(treatment, set()):
            dfs(p, outcome, [treatment, p], came_from_child=False)
        return paths

    def find_backdoor_adjustment_set(
        self, treatment: str, outcome: str
    ) -> Optional[set[str]]:
        """Findet eine gültige Backdoor-Adjustment-Menge nach Pearl.

        Vereinfachte Heuristik (klassisches Backdoor-Kriterium):
            Z = Eltern(treatment) ∖ Nachfahren(treatment)

        Diese Menge erfüllt das Backdoor-Kriterium in den meisten praktischen
        Fällen (sie blockiert alle Backdoor-Pfade von X nach Y, sofern
        keine Nachfahren von X betrachtet werden).
        """
        if treatment not in self._parents or outcome not in self._parents:
            return None
        candidates = self.parents(treatment) - self.descendants(treatment) - {outcome}
        return candidates

    # ── do-Operator + Backdoor-Adjustierung ──────────────────────
    def do_backdoor(
        self,
        P_y_given_x_z: Callable[[str, str, dict[str, str]], float],
        P_z: Callable[[dict[str, str]], float],
        z_value_space: dict[str, list[str]],
        treatment: str,
        outcome: str,
        x: str,
        y: str,
    ) -> float:
        """Berechnet P(Y=y | do(X=x)) via exakter Backdoor-Adjustierung.

        Args:
            P_y_given_x_z: Funktion (x, y, z_dict) → Wahrscheinlichkeit
            P_z:           Funktion (z_dict) → Wahrscheinlichkeit
            z_value_space: {z_var: [möglicher_wert, ...]}
            treatment:     Name der Treatment-Variablen X
            outcome:       Name der Outcome-Variablen Y
            x, y:          konkrete Werte der Variablen
        """
        z_set = self.find_backdoor_adjustment_set(treatment, outcome)
        if z_set is None:
            raise CausalGraphError(
                f"Treatment '{treatment}' oder Outcome '{outcome}' nicht im Graph."
            )

        # Kartesisches Produkt aller Z-Werte
        from itertools import product

        z_vars = sorted(z_set)
        if not z_vars:
            return P_y_given_x_z(x, y, {})

        domains = [z_value_space[z] for z in z_vars]
        total = 0.0
        for combo in product(*domains):
            z_dict = dict(zip(z_vars, combo))
            total += P_y_given_x_z(x, y, z_dict) * P_z(z_dict)
        return total

    def do_backdoor_monte_carlo(
        self,
        P_y_given_x_z: Callable[[str, str, dict[str, str]], float],
        P_z: Callable[[dict[str, str]], float],
        z_sampler: Callable[[], dict[str, str]],
        x: str,
        y: str,
        n_samples: int = 10_000,
        seed: Optional[int] = None,
    ) -> float:
        """Approximiert P(Y=y | do(X=x)) via Monte-Carlo.

        Vermeidet exponentielle Komplexität bei vielen Backdoor-Variablen.
        """
        import random as _random
        rng = _random.Random(seed)
        # rng wird vom z_sampler optional verwendet
        total = 0.0
        for _ in range(n_samples):
            z = z_sampler()
            total += P_y_given_x_z(x, y, z) * P_z(z)
        return total / n_samples

    # ── Serialisierung ────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "nodes": sorted(self._parents.keys()),
            "edges": sorted(self.edges()),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CausalGraph":
        g = cls()
        for n in d.get("nodes", []):
            g.add_node(n)
        for src, dst in d.get("edges", []):
            g.add_edge(src, dst)
        return g

    def to_dot(self) -> str:
        """Graphviz-DOT-Repräsentation."""
        lines = ["digraph CausalGraph {", "  rankdir=LR;"]
        for n in sorted(self._parents):
            lines.append(f'  "{n}";')
        for src, dst in sorted(self.edges()):
            lines.append(f'  "{src}" -> "{dst}";')
        lines.append("}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"CausalGraph(nodes={len(self._parents)}, edges={len(self.edges())})"
