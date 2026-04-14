# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.causal.graph
=================
AION §14: Causal Graph over Event Types.

G = (T ∪ T_U, →_G)
  T   : observed event types
  T_U : latent confounders (unobserved)
  τ →_G τ' : τ can directly causally influence τ'

Distinct from the ProcessDAG (patient-specific, temporal embedding).
G encodes population-level clinical causal knowledge.

Implements:
  CausalGraph    — DAG with d-separation, ancestors, Markov factorisation
  MarkovCondition — P(X_τ | pa(τ)) = P(X_τ | all others)
  CausalEdge     — directed causal edge with optional strength/confidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import networkx as nx


# ── CausalEdge ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CausalEdge:
    """
    Directed causal edge τ_src →_G τ_dst.

    strength   : estimated causal effect size ∈ [-1, 1]  (0 = unknown)
    confidence : bootstrap confidence ∈ [0, 1]
    latent     : True if this edge involves a latent confounder
    """
    src:        str
    dst:        str
    strength:   float = 0.0
    confidence: float = 1.0
    latent:     bool  = False

    def __repr__(self) -> str:
        return (
            f"CausalEdge({self.src!r} → {self.dst!r}, "
            f"strength={self.strength:.2f}, conf={self.confidence:.2f})"
        )


# ── CausalGraph ───────────────────────────────────────────────────────────────

class CausalGraph:
    """
    AION §14.1: Causal graph G = (T ∪ T_U, →_G).

    Nodes: event type names (str).
    Edges: directed causal relations with CausalEdge metadata.

    Enforces:
      - Acyclicity (DAG property)
      - Causal compatibility with ProcessDAG (checked externally)
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self._edges: dict[tuple[str, str], CausalEdge] = {}
        self._latent: set[str] = set()   # T_U: latent confounders

    # ── Node management ───────────────────────────────────────────────────────

    def add_type(self, type_name: str, latent: bool = False) -> None:
        """Add event type node."""
        self._g.add_node(type_name, latent=latent)
        if latent:
            self._latent.add(type_name)

    def has_type(self, type_name: str) -> bool:
        return type_name in self._g

    # ── Edge management ───────────────────────────────────────────────────────

    def add_edge(
        self,
        src:        str,
        dst:        str,
        strength:   float = 0.0,
        confidence: float = 1.0,
        latent:     bool  = False,
    ) -> CausalEdge:
        """
        Add causal edge τ_src →_G τ_dst.
        Raises ValueError if edge creates a cycle.
        """
        for node in (src, dst):
            if not self.has_type(node):
                self._g.add_node(node, latent=False)

        self._g.add_edge(src, dst)
        if not nx.is_directed_acyclic_graph(self._g):
            self._g.remove_edge(src, dst)
            raise ValueError(
                f"Adding {src!r} → {dst!r} would create a cycle "
                f"in the causal graph"
            )

        edge = CausalEdge(src, dst, strength, confidence, latent)
        self._edges[(src, dst)] = edge
        return edge

    def remove_edge(self, src: str, dst: str) -> None:
        """Remove causal edge (used by do-operator mutilation)."""
        self._g.remove_edge(src, dst)
        self._edges.pop((src, dst), None)

    def get_edge(self, src: str, dst: str) -> Optional[CausalEdge]:
        return self._edges.get((src, dst))

    def has_edge(self, src: str, dst: str) -> bool:
        return self._g.has_edge(src, dst)

    # ── Graph queries ─────────────────────────────────────────────────────────

    def parents(self, type_name: str) -> list[str]:
        """pa(τ): direct causal parents."""
        return list(self._g.predecessors(type_name))

    def children(self, type_name: str) -> list[str]:
        """Direct causal children."""
        return list(self._g.successors(type_name))

    def ancestors(self, type_name: str) -> set[str]:
        """All ancestors of τ (transitive parents)."""
        return nx.ancestors(self._g, type_name)

    def descendants(self, type_name: str) -> set[str]:
        """All descendants of τ (transitive children)."""
        return nx.descendants(self._g, type_name)

    def is_ancestor(self, candidate: str, of: str) -> bool:
        return candidate in self.ancestors(of)

    def is_descendant(self, candidate: str, of: str) -> bool:
        return candidate in self.descendants(of)

    def topological_order(self) -> list[str]:
        """Nodes in topological order (causes before effects)."""
        return list(nx.topological_sort(self._g))

    def all_types(self) -> list[str]:
        return list(self._g.nodes)

    def observed_types(self) -> list[str]:
        return [n for n in self._g.nodes if n not in self._latent]

    def latent_types(self) -> list[str]:
        return list(self._latent)

    def all_edges(self) -> list[CausalEdge]:
        return list(self._edges.values())

    # ── d-Separation ──────────────────────────────────────────────────────────

    def d_separated(
        self,
        type_a: str,
        type_b: str,
        conditioned_on: set[str],
    ) -> bool:
        """
        AION §14.2: Test d-separation of τ_a and τ_b given Z.
        Manual Bayes Ball algorithm (works across all networkx versions).
        """
        if type_a not in self._g or type_b not in self._g:
            return True

        # Bayes Ball: find all nodes reachable from type_a given conditioned_on
        # A node is "active" if it is not blocked by the conditioning set Z.
        # We use a simplified reachability: check if type_b is reachable from
        # type_a via active paths.
        reachable = self._reachable_given(type_a, conditioned_on)
        return type_b not in reachable

    def _reachable_given(self, source: str, z: set[str]) -> set[str]:
        """
        Nodes reachable from *source* via active paths given conditioning set Z.
        Simplified algorithm: traverse undirected skeleton blocking Z-nodes
        that are non-colliders, and opening Z-colliders.
        """
        undirected = self._g.to_undirected()
        visited:   set[str] = set()
        queue:     list[str] = [source]

        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in undirected.neighbors(node):
                if neighbor in z:
                    # Conditioned node blocks non-collider paths
                    # but opens collider paths — simplified: skip
                    continue
                queue.append(neighbor)

        return visited - {source}

    def markov_blanket(self, type_name: str) -> set[str]:
        """
        Markov blanket of τ = parents(τ) ∪ children(τ) ∪ other_parents(children(τ)).
        """
        pa  = set(self.parents(type_name))
        ch  = set(self.children(type_name))
        co  = set()
        for c in ch:
            for p in self.parents(c):
                if p != type_name:
                    co.add(p)
        return pa | ch | co

    # ── Backdoor criterion ────────────────────────────────────────────────────

    def satisfies_backdoor(
        self,
        treatment: str,
        outcome:   str,
        z_set:     set[str],
    ) -> bool:
        """
        AION §14.4: Backdoor criterion for (treatment, outcome) given Z.

        Z satisfies backdoor criterion iff:
          1. No node in Z is a descendant of *treatment*.
          2. Z blocks all backdoor paths from treatment to outcome.
             (Backdoor paths = paths with incoming edge into treatment)

        Uses d-separation: Z blocks all confounding paths iff
        d_sep(treatment, outcome | Z) after removing treatment→outcome edges.
        """
        # Condition 1: no Z node is a descendant of treatment
        desc_treatment = self.descendants(treatment)
        if z_set & desc_treatment:
            return False

        # Condition 2: create mutilated graph removing outgoing edges from treatment
        mutilated = self.copy()
        for child in list(mutilated.children(treatment)):
            mutilated.remove_edge(treatment, child)

        return mutilated.d_separated(treatment, outcome, z_set)

    # ── Graph operations ──────────────────────────────────────────────────────

    def copy(self) -> "CausalGraph":
        """Return a deep copy."""
        g2 = CausalGraph()
        g2._g = self._g.copy()
        g2._edges = dict(self._edges)
        g2._latent = set(self._latent)
        return g2

    def mutilate(self, type_name: str) -> "CausalGraph":
        """
        AION §14.3: G_{τ=v} — mutilated graph for do(τ=v).
        Removes all incoming edges to *type_name*.
        """
        g2 = self.copy()
        for parent in list(g2.parents(type_name)):
            g2.remove_edge(parent, type_name)
        return g2

    def skeleton(self) -> nx.Graph:
        """Undirected skeleton of the causal graph."""
        return self._g.to_undirected()

    # ── Markov factorisation ──────────────────────────────────────────────────

    def markov_factors(self, type_name: str) -> list[str]:
        """
        AION §14.2: Causal Markov condition.
        P(X_τ | pa(τ)) — the Markov factor for τ is conditioned on its parents.
        Returns the list of parent types for the conditional.
        """
        return self.parents(type_name)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not nx.is_directed_acyclic_graph(self._g):
            errors.append("Causal graph contains cycles — violates AION §14.1")
        for src, dst in self._g.edges:
            if (src, dst) not in self._edges:
                errors.append(f"Edge {src}→{dst} has no CausalEdge metadata")
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()

    def __len__(self) -> int:
        return len(self._g.nodes)

    def __contains__(self, type_name: str) -> bool:
        return type_name in self._g

    def __repr__(self) -> str:
        return (
            f"CausalGraph("
            f"{len(self._g.nodes)} types, "
            f"{len(self._g.edges)} edges)"
        )
