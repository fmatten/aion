# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
# aion/causal_learn/pc_algorithm.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
PC-Algorithmus und GES nach §15 des AION-Papers.
Stdlib-only: kein DoWhy, kein NetworkX.

Implementiert:
  §15.1  Grundannahmen (Treueannahme, kausale Suffizienz)
  §15.2  Statistische Grundlage (bedingte Unabhaengigkeit via Korrelation)
  §15.3  PC-Algorithmus (Skelettlernen + V-Struktur-Orientierung)
  §15.5  Kantenkonfidenzen und Bootstrap-Validierung
  §15.6  Integration in CausalGraph
"""
from __future__ import annotations
import math, random, logging
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

log = logging.getLogger(__name__)


# ── §15.2 Statistische Tests ──────────────────────────────────────────────

def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0

def _pearson_r(x: list, y: list) -> float:
    n = len(x)
    if n < 3: return 0.0
    mx, my = _mean(x), _mean(y)
    num  = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx   = math.sqrt(sum((a - mx)**2 for a in x))
    dy   = math.sqrt(sum((b - my)**2 for b in y))
    if dx < 1e-10 or dy < 1e-10: return 0.0
    return num / (dx * dy)

def _partial_corr(x: list, y: list, z_vals: list[list]) -> float:
    """Partielle Korrelation r(X,Y|Z) via sukzessive Residualbildung."""
    rx, ry = list(x), list(y)
    for z in z_vals:
        if not z: continue
        r_xz = _pearson_r(rx, z)
        r_yz = _pearson_r(ry, z)
        mz   = _mean(z)
        sz   = math.sqrt(sum((v - mz)**2 for v in z) / max(len(z)-1, 1))
        if sz < 1e-10: continue
        rx = [rx[i] - r_xz * (z[i] - mz) / sz for i in range(len(rx))]
        ry = [ry[i] - r_yz * (z[i] - mz) / sz for i in range(len(ry))]
    return _pearson_r(rx, ry)

def _fisher_z(r: float, n: int) -> float:
    """Fisher-Z-Transformierung fuer Signifikanztest."""
    r = max(-0.9999, min(0.9999, r))
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(max(n - 3, 1))
    return abs(z) / se  # z-Score

def is_cond_independent(
    x_vals: list, y_vals: list,
    z_vals: list[list],
    alpha: float = 0.05,
) -> bool:
    """
    Bedingte Unabhaengigkeit X _||_ Y | Z via partieller Korrelation.
    Schwellwert: I(X;Y|Z) <= epsilon_ind (§15.2)
    """
    if len(x_vals) < 5: return False
    r  = _partial_corr(x_vals, y_vals, z_vals)
    zs = _fisher_z(r, len(x_vals))
    # kritischer z-Wert fuer alpha=0.05: 1.96
    z_crit = {0.01: 2.576, 0.05: 1.96, 0.1: 1.645}.get(alpha, 1.96)
    return zs < z_crit


# ── §15.3 PC-Algorithmus ─────────────────────────────────────────────────

@dataclass
class PCResult:
    """Ergebnis des PC-Algorithmus."""
    edges:          set   = field(default_factory=set)   # gerichtete Kanten
    skeleton:       set   = field(default_factory=set)   # ungerichtetes Skelett
    sep_sets:       dict  = field(default_factory=dict)  # Sep(X,Y)
    v_structures:   list  = field(default_factory=list)  # X → Z ← Y
    n_nodes:        int   = 0
    n_edges:        int   = 0

    def to_dict(self) -> dict:
        return {
            "edges":        [list(e) for e in self.edges],
            "n_nodes":      self.n_nodes,
            "n_edges":      self.n_edges,
            "v_structures": self.v_structures,
        }


def pc_algorithm(
    data:  dict[str, list],
    alpha: float = 0.05,
    max_cond_set: int = 3,
) -> PCResult:
    """
    PC-Algorithmus nach §15.3 (Peter-Clark).

    Args:
        data:  {node_name: [beobachtete Werte]}
        alpha: Signifikanzschwelle fuer Unabhaengigkeitstests
        max_cond_set: maximale Konditionierungsmengengroesse

    Returns:
        PCResult mit gelerntem Graphen
    """
    nodes = list(data.keys())
    n     = len(nodes)
    log.info("PC-Algorithmus: %d Knoten, alpha=%.3f", n, alpha)

    # Phase 1: Skelettlernen
    adj  = {i: set(range(n)) - {i} for i in range(n)}
    seps = {}

    for size in range(max_cond_set + 1):
        changed = False
        for i, j in list(combinations(range(n), 2)):
            if j not in adj[i]: continue
            neighbors_i = adj[i] - {j}
            if len(neighbors_i) < size: continue
            for z_idx in combinations(neighbors_i, size):
                xi = data[nodes[i]]
                xj = data[nodes[j]]
                xz = [data[nodes[k]] for k in z_idx]
                if is_cond_independent(xi, xj, xz, alpha):
                    adj[i].discard(j)
                    adj[j].discard(i)
                    seps[(i,j)] = seps[(j,i)] = set(z_idx)
                    changed = True
                    log.debug("Kante %s-%s entfernt | Z=%s",
                              nodes[i], nodes[j],
                              [nodes[k] for k in z_idx])
                    break
            if j not in adj[i]: break

    skeleton = {(min(i,j), max(i,j)) for i in range(n) for j in adj[i]}

    # Phase 2: V-Strukturen orientieren (X → Z ← Y)
    directed = set()
    v_structs = []
    for i, k, j in combinations(range(n), 3):
        pairs = [(i,k),(k,j)]
        if all((min(a,b),max(a,b)) in skeleton for a,b in pairs):
            if (min(i,j),max(i,j)) not in skeleton:
                sep = seps.get((i,j), set())
                if k not in sep:
                    directed.add((i,k))
                    directed.add((j,k))
                    v_structs.append([nodes[i], nodes[k], nodes[j]])
                    log.debug("V-Struktur: %s->%s<-%s",
                              nodes[i], nodes[k], nodes[j])

    # Ungerichtete Kanten mit Knotenindex-Reihenfolge auffuellen
    all_edges = set()
    for (i,j) in skeleton:
        if (i,j) in directed:    all_edges.add((nodes[i], nodes[j]))
        elif (j,i) in directed:  all_edges.add((nodes[j], nodes[i]))
        else:                    all_edges.add((nodes[i], nodes[j]))

    result = PCResult(
        edges=all_edges, skeleton=skeleton,
        sep_sets=seps, v_structures=v_structs,
        n_nodes=n, n_edges=len(all_edges),
    )
    log.info("PC fertig: %d Kanten, %d V-Strukturen",
             len(all_edges), len(v_structs))
    return result


# ── §15.5 Bootstrap-Kantenkonfidenzen ────────────────────────────────────

@dataclass
class BootstrapResult:
    """Bootstrap-Ergebnis nach §15.5."""
    edge_confidences: dict[tuple, float]  # (X,Y) -> P(X->Y in Ghat)
    stable_edges:     set[tuple]          # Kanten mit conf >= gamma
    n_bootstrap:      int
    gamma:            float

    def to_dict(self) -> dict:
        return {
            "stable_edges": [list(e) for e in self.stable_edges],
            "edge_confidences": {
                f"{a}->{b}": round(c, 4)
                for (a,b), c in sorted(
                    self.edge_confidences.items(),
                    key=lambda x: -x[1]
                )
            },
            "n_bootstrap": self.n_bootstrap,
            "gamma_threshold": self.gamma,
        }


def bootstrap_pc(
    data:       dict[str, list],
    n_bootstrap: int = 100,
    gamma:      float = 0.5,
    alpha:      float = 0.05,
) -> BootstrapResult:
    """
    Bootstrap-Kantenkonfidenzen nach §15.5.

    c_hat_G(tau_i, tau_j) = (1/B) * sum_b 1[tau_i->tau_j in G_hat*(b)]

    Stabiler Graph: G_hat_gamma = {(i,j) | c_hat >= gamma}
    """
    nodes   = list(data.keys())
    counts  = defaultdict(int)
    n_obs   = len(next(iter(data.values())))

    log.info("Bootstrap-PC: B=%d, gamma=%.2f", n_bootstrap, gamma)

    for b in range(n_bootstrap):
        # Resample mit Zuruecklegen
        idx = [random.randint(0, n_obs - 1) for _ in range(n_obs)]
        sample = {k: [v[i] for i in idx] for k, v in data.items()}
        result = pc_algorithm(sample, alpha=alpha)
        for edge in result.edges:
            counts[edge] += 1

    confidences = {edge: cnt / n_bootstrap for edge, cnt in counts.items()}
    stable = {e for e, c in confidences.items() if c >= gamma}

    log.info("Bootstrap fertig: %d stabile Kanten (gamma=%.2f)",
             len(stable), gamma)

    return BootstrapResult(
        edge_confidences=confidences,
        stable_edges=stable,
        n_bootstrap=n_bootstrap,
        gamma=gamma,
    )
