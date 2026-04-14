# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.causal.structure
=====================
AION §15: Causal Structure Learning.

PC Algorithm (Peter-Clark):
  Phase 1: Skeleton learning via conditional independence tests
  Phase 2: V-structure orientation + Meek rules propagation

GES (Greedy Equivalence Search):
  Score-based learning using BIC.

Bootstrap validation:
  B resamples → edge confidence c_G(τ_i, τ_j) ∈ [0,1]
  Stable causal graph at threshold γ_G.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

import networkx as nx

from ..core.event import EventSet
from ..core.types import TypeHierarchy, default_hierarchy
from .graph import CausalGraph, CausalEdge


# ── Conditional Independence Test ─────────────────────────────────────────────

class ConditionalIndependenceTest:
    """
    AION §15.2: Empirical conditional independence test.

    For binary event-type variables (presence / absence per patient):
    Uses mutual information I(X_i; X_j | Z) with threshold ε.

    For continuous attributes: uses partial correlation.
    """

    def __init__(
        self,
        event_set:  EventSet,
        hierarchy:  Optional[TypeHierarchy] = None,
        eps:        float = 0.05,   # ε_ind: independence threshold
    ) -> None:
        self._es  = event_set
        self._h   = hierarchy or default_hierarchy()
        self.eps  = eps
        self._cache: dict = {}

    def _patient_vector(self, type_name: str) -> dict[str, int]:
        """Binary vector: patient_id → 1 if has event of type, else 0."""
        having = {e.patient_id for e in self._es.by_type(type_name)}
        return {pid: int(pid in having) for pid in self._es.all_patients}

    def _joint_freq(
        self,
        vec_i: dict[str, int],
        vec_j: dict[str, int],
        vec_z: Optional[dict[str, int]] = None,
    ) -> dict[tuple, float]:
        """Compute joint frequency table."""
        pids = list(vec_i.keys())
        counts: dict[tuple, int] = {}
        for pid in pids:
            xi = vec_i[pid]
            xj = vec_j[pid]
            xz = vec_z[pid] if vec_z else None
            key = (xi, xj, xz) if xz is not None else (xi, xj)
            counts[key] = counts.get(key, 0) + 1
        n = len(pids)
        return {k: v / n for k, v in counts.items()}

    def mutual_information(
        self,
        type_i: str,
        type_j: str,
    ) -> float:
        """I(X_i; X_j) — unconditional mutual information (nats)."""
        vi = self._patient_vector(type_i)
        vj = self._patient_vector(type_j)
        freq = self._joint_freq(vi, vj)
        pi   = {xi: sum(f for (xi2, xj2), f in freq.items() if xi2 == xi)
                for xi in (0, 1)}
        pj   = {xj: sum(f for (xi2, xj2), f in freq.items() if xj2 == xj)
                for xj in (0, 1)}
        mi = 0.0
        for (xi, xj), pij in freq.items():
            if pij > 0 and pi[xi] > 0 and pj[xj] > 0:
                mi += pij * math.log(pij / (pi[xi] * pj[xj]))
        return max(0.0, mi)

    def conditional_mi(
        self,
        type_i: str,
        type_j: str,
        z_set:  set[str],
    ) -> float:
        """
        I(X_i; X_j | Z) — conditional mutual information.
        Approximation for binary variables: average MI per Z-stratum.
        """
        if not z_set:
            return self.mutual_information(type_i, type_j)

        # For simplicity, condition on the first Z type only
        z_type = next(iter(z_set))
        vi = self._patient_vector(type_i)
        vj = self._patient_vector(type_j)
        vz = self._patient_vector(z_type)

        total_cmi = 0.0
        for z_val in (0, 1):
            pids_z = [pid for pid in vi if vz[pid] == z_val]
            if len(pids_z) < 2:
                continue
            pz = len(pids_z) / len(vi)
            # Compute MI within stratum
            vi_z = {pid: vi[pid] for pid in pids_z}
            vj_z = {pid: vj[pid] for pid in pids_z}
            freq = self._joint_freq(vi_z, vj_z)
            pi_z = {xi: sum(f for (xi2,_), f in freq.items() if xi2==xi) for xi in (0,1)}
            pj_z = {xj: sum(f for (_,xj2), f in freq.items() if xj2==xj) for xj in (0,1)}
            mi_z = 0.0
            for (xi, xj), pij in freq.items():
                if pij > 0 and pi_z[xi] > 0 and pj_z[xj] > 0:
                    mi_z += pij * math.log(pij / (pi_z[xi] * pj_z[xj]))
            total_cmi += pz * max(0.0, mi_z)

        return total_cmi

    def independent(
        self,
        type_i: str,
        type_j: str,
        z_set:  set[str] = frozenset(),
    ) -> bool:
        """
        True iff I(X_i; X_j | Z) ≤ ε_ind.
        """
        key = (type_i, type_j, frozenset(z_set))
        if key not in self._cache:
            cmi = self.conditional_mi(type_i, type_j, set(z_set))
            self._cache[key] = cmi <= self.eps
        return self._cache[key]


# ── PCAlgorithm ───────────────────────────────────────────────────────────────

@dataclass
class SkeletonResult:
    skeleton:       nx.Graph
    sep_sets:       dict[tuple[str, str], set[str]]   # Sep(i,j)
    removed_edges:  list[tuple[str, str]]


class PCAlgorithm:
    """
    AION §15.3: PC Algorithm (Peter-Clark).

    Phase 1: Skeleton learning — remove edges for conditionally independent pairs.
    Phase 2: V-structure orientation + Meek rules.

    Returns a CausalGraph representing the learned CPDAG
    (completed partially directed acyclic graph).
    """

    def __init__(
        self,
        ci_test:    ConditionalIndependenceTest,
        max_cond:   int = 3,   # max conditioning set size
    ) -> None:
        self.ci_test  = ci_test
        self.max_cond = max_cond

    def learn_skeleton(
        self,
        type_names: list[str],
    ) -> SkeletonResult:
        """
        Phase 1: Learn undirected skeleton by iterative edge removal.
        """
        # Start with complete undirected graph
        skel = nx.Graph()
        skel.add_nodes_from(type_names)
        skel.add_edges_from(combinations(type_names, 2))

        sep_sets: dict[tuple[str, str], set[str]] = {}
        removed: list[tuple[str, str]] = []

        for cond_size in range(0, self.max_cond + 1):
            for (i, j) in list(skel.edges):
                # Adjacency set of i, excluding j
                adj_i = set(skel.neighbors(i)) - {j}
                if len(adj_i) < cond_size:
                    continue
                # Test all subsets of adj_i of size cond_size
                for z_set in _subsets(adj_i, cond_size):
                    if self.ci_test.independent(i, j, set(z_set)):
                        skel.remove_edge(i, j)
                        sep_sets[(i, j)] = set(z_set)
                        sep_sets[(j, i)] = set(z_set)
                        removed.append((i, j))
                        break
                else:
                    continue
                break

        return SkeletonResult(skel, sep_sets, removed)

    def orient_v_structures(
        self,
        skeleton: nx.Graph,
        sep_sets: dict[tuple[str, str], set[str]],
    ) -> nx.DiGraph:
        """
        Phase 2a: Orient v-structures i → k ← j
        where (i,j) ∉ skeleton and k ∉ Sep(i,j).
        """
        dg = nx.DiGraph()
        dg.add_nodes_from(skeleton.nodes)
        # Start with all edges undirected (represented as both directions)
        for (i, j) in skeleton.edges:
            dg.add_edge(i, j)
            dg.add_edge(j, i)

        # Find and orient v-structures
        for node in skeleton.nodes:
            parents_of = list(skeleton.neighbors(node))
            for (i, j) in combinations(parents_of, 2):
                if skeleton.has_edge(i, j):
                    continue   # i and j are adjacent → not a v-structure
                sep = sep_sets.get((i, j), sep_sets.get((j, i), set()))
                if node not in sep:
                    # i → node ← j  (collider / v-structure)
                    # Remove reverse edges to orient
                    if dg.has_edge(node, i):
                        dg.remove_edge(node, i)
                    if dg.has_edge(node, j):
                        dg.remove_edge(node, j)

        return dg

    def apply_meek_rules(self, dg: nx.DiGraph) -> nx.DiGraph:
        """
        Phase 2b: Propagate orientation using Meek's four rules.
        Simplified: apply rules until no further orientations possible.
        """
        changed = True
        while changed:
            changed = False

            for (i, j) in list(dg.edges):
                # Skip already oriented edges (only i→j, not j→i)
                if not dg.has_edge(j, i):
                    continue  # already directed

                # Meek Rule 1: orient i-j into i→j to avoid a new v-structure
                # If k→i and k-j is not in graph
                for k in list(dg.predecessors(i)):
                    if dg.has_edge(i, k):
                        continue   # k-i undirected
                    if not dg.has_edge(j, k) and not dg.has_edge(k, j):
                        # Orient j→ instead of i-j to avoid cycle
                        dg.remove_edge(j, i)
                        changed = True
                        break

        return dg

    def run(self, type_names: list[str]) -> CausalGraph:
        """
        Full PC algorithm: skeleton + orientation.
        Returns a CausalGraph.
        """
        result  = self.learn_skeleton(type_names)
        dg      = self.orient_v_structures(result.skeleton, result.sep_sets)
        dg      = self.apply_meek_rules(dg)

        graph   = CausalGraph()
        for n in dg.nodes:
            graph.add_type(n)

        for (src, dst) in dg.edges:
            if not dg.has_edge(dst, src):   # directed only
                try:
                    graph.add_edge(src, dst, confidence=1.0)
                except ValueError:
                    pass   # skip cycle-creating edges

        return graph


# ── Bootstrap Validation ──────────────────────────────────────────────────────

@dataclass
class EdgeConfidence:
    """
    AION §15.4: c_G(τ_i, τ_j) = fraction of bootstrap graphs with edge τ_i → τ_j.
    """
    src:        str
    dst:        str
    confidence: float   # ∈ [0,1]

    def __repr__(self) -> str:
        return f"EdgeConf({self.src!r}→{self.dst!r}: {self.confidence:.2f})"


@dataclass
class BootstrapResult:
    """
    AION §15.4: Result of bootstrap causal structure learning.

    edge_confidences : all edges with c_G ≥ threshold
    stable_graph     : G_{γ_G} with edges above threshold
    n_resamples      : B
    """
    edge_confidences: list[EdgeConfidence]
    stable_graph:     CausalGraph
    n_resamples:      int
    threshold:        float


class BootstrapCausalLearner:
    """
    AION §15.4: Bootstrap validation of causal structure.

    1. Draw B bootstrap resamples of patients
    2. Run PC algorithm on each resample
    3. Estimate edge confidence as fraction of runs containing edge
    4. Return stable graph G_{γ_G}
    """

    def __init__(
        self,
        event_set:  EventSet,
        type_names: list[str],
        hierarchy:  Optional[TypeHierarchy] = None,
        eps:        float = 0.05,
        max_cond:   int   = 3,
        seed:       Optional[int] = None,
    ) -> None:
        self._es         = event_set
        self.type_names  = type_names
        self._h          = hierarchy or default_hierarchy()
        self.eps         = eps
        self.max_cond    = max_cond
        self._rng        = random.Random(seed)

    def _resample_event_set(self) -> EventSet:
        """Bootstrap resample: sample patients with replacement."""
        all_pids = list(self._es.all_patients)
        sampled  = [self._rng.choice(all_pids) for _ in all_pids]
        new_es   = EventSet(hierarchy=self._h)
        import uuid
        for pid in sampled:
            for e in self._es.by_patient(pid):
                # Create copy with new ID to avoid duplicates
                new_attrs = dict(e.attributes)
                new_attrs["id"] = str(uuid.uuid4())
                from ..core.event import ClinicalEvent
                new_e = ClinicalEvent(
                    patient_id=e.patient_id,
                    stay_id=e.stay_id,
                    type=e.type,
                    tau=e.tau,
                    attributes=new_attrs,
                    refs=e.refs,
                    confidence=e.confidence,
                )
                new_es.add(new_e)
        return new_es

    def run(
        self,
        n_resamples: int = 100,
        threshold:   float = 0.5,
    ) -> BootstrapResult:
        """
        Run bootstrap causal learning.
        Returns stable graph at confidence >= threshold.
        """
        edge_counts: dict[tuple[str, str], int] = {}

        for _ in range(n_resamples):
            resampled = self._resample_event_set()
            ci_test   = ConditionalIndependenceTest(resampled, self._h, self.eps)
            pc        = PCAlgorithm(ci_test, self.max_cond)
            graph_b   = pc.run(self.type_names)

            for edge in graph_b.all_edges():
                key = (edge.src, edge.dst)
                edge_counts[key] = edge_counts.get(key, 0) + 1

        # Compute confidences
        confidences = [
            EdgeConfidence(src=src, dst=dst,
                           confidence=count / n_resamples)
            for (src, dst), count in edge_counts.items()
        ]
        confidences.sort(key=lambda ec: ec.confidence, reverse=True)

        # Build stable graph G_{γ_G}
        stable = CausalGraph()
        for t in self.type_names:
            stable.add_type(t)
        for ec in confidences:
            if ec.confidence >= threshold:
                try:
                    stable.add_edge(ec.src, ec.dst, confidence=ec.confidence)
                except ValueError:
                    pass   # skip cycle-creating edges

        return BootstrapResult(
            edge_confidences=confidences,
            stable_graph=stable,
            n_resamples=n_resamples,
            threshold=threshold,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _subsets(items: set, size: int):
    """Generate all subsets of *items* of exactly *size*."""
    return combinations(items, size)
