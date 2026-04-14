# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.core.process
=================
AION §8: Hierarchical Process Model.

ProcessDAG  — G_{k,i} = (E_{k,i}, →) for patient p_k in stay a_{k,i}
              Encodes subprocess relationships with Allen CONTAINS/DURING.
ProcessIndex — lookup sub(e), desc(e), parent(e) efficiently.

Key invariants enforced:
  1. Acyclicity  : G_{k,i} is a DAG
  2. Temporal    : e1 → e2  ⟹  During(e2, e1)   (AION §8.1)
  3. Type conf.  : type(e2) ∈ comp(type(e1))      (AION §8.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Iterator
import networkx as nx

from .allen import AllenRelation, holds, Interval
from .event  import ClinicalEvent, EventSet
from .types  import TypeHierarchy, default_hierarchy


# ── ProcessDAG ────────────────────────────────────────────────────────────────

class ProcessDAG:
    """
    AION §8.1: Process DAG for a single (patient, stay).

    G_{k,i} = (E_{k,i}, →)
    e1 → e2  means "e2 is a direct subprocess of e1"

    The DAG is type-conformant if for all edges e1→e2:
        type(e2) ∈ comp(type(e1))   (AION §8.2)
    """

    def __init__(
        self,
        patient_id: str,
        stay_id:    str,
        hierarchy:  Optional[TypeHierarchy] = None,
    ) -> None:
        self.patient_id = patient_id
        self.stay_id    = stay_id
        self._h         = hierarchy or default_hierarchy()
        self._g:  nx.DiGraph = nx.DiGraph()
        self._events: dict[str, ClinicalEvent] = {}

    # ── Event management ──────────────────────────────────────────────────────

    def add_event(self, event: ClinicalEvent) -> None:
        """Register an event as a node (no edges yet)."""
        if event.patient_id != self.patient_id:
            raise ValueError(
                f"Event patient {event.patient_id!r} != DAG patient {self.patient_id!r}"
            )
        if event.stay_id != self.stay_id:
            raise ValueError(
                f"Event stay {event.stay_id!r} != DAG stay {self.stay_id!r}"
            )
        self._g.add_node(event.id)
        self._events[event.id] = event

    def add_subprocess(
        self,
        parent_id: str,
        child_id:  str,
        validate:  bool = True,
    ) -> None:
        """
        Add edge parent → child (child is direct subprocess of parent).

        validate=True: enforce AION §8.1 invariants.
        """
        if parent_id not in self._events:
            raise KeyError(f"Unknown parent event: {parent_id!r}")
        if child_id not in self._events:
            raise KeyError(f"Unknown child event: {child_id!r}")

        parent = self._events[parent_id]
        child  = self._events[child_id]

        if validate:
            # 1. Temporal: During(child, parent)
            if not holds(AllenRelation.DURING, child.tau, parent.tau):
                raise ValueError(
                    f"AION §8.1 violation: During({child_id}, {parent_id}) "
                    f"not satisfied. "
                    f"Child: {child.tau!r}, Parent: {parent.tau!r}"
                )
            # 2. Type conformance
            if not self._h.composition_valid(parent.type, child.type):
                raise ValueError(
                    f"AION §8.2 violation: type '{child.type}' "
                    f"not in comp('{parent.type}')"
                )

        self._g.add_edge(parent_id, child_id)

        # 3. Acyclicity
        if not nx.is_directed_acyclic_graph(self._g):
            self._g.remove_edge(parent_id, child_id)
            raise ValueError(
                f"AION §8.1 violation: adding {parent_id}→{child_id} "
                f"creates a cycle"
            )

    # ── Hierarchy queries ─────────────────────────────────────────────────────

    def sub(self, event_id: str) -> list[ClinicalEvent]:
        """sub(e): direct subprocess events of e."""
        return [
            self._events[c]
            for c in self._g.successors(event_id)
            if c in self._events
        ]

    def desc(self, event_id: str) -> list[ClinicalEvent]:
        """desc(e): all (transitive) descendant subprocess events."""
        return [
            self._events[d]
            for d in nx.descendants(self._g, event_id)
            if d in self._events
        ]

    def parent(self, event_id: str) -> Optional[ClinicalEvent]:
        """Immediate parent process of e (None = top-level)."""
        parents = list(self._g.predecessors(event_id))
        if not parents:
            return None
        return self._events.get(parents[0])

    def procs(self, event_id: str) -> list[ClinicalEvent]:
        """procs(e): all ancestor processes (from immediate parent up to root)."""
        return [
            self._events[a]
            for a in nx.ancestors(self._g, event_id)
            if a in self._events
        ]

    def roots(self) -> list[ClinicalEvent]:
        """Top-level processes (nodes without predecessors)."""
        return [
            self._events[n]
            for n in self._g.nodes
            if self._g.in_degree(n) == 0 and n in self._events
        ]

    def leaves(self) -> list[ClinicalEvent]:
        """Leaf events (nodes without successors)."""
        return [
            self._events[n]
            for n in self._g.nodes
            if self._g.out_degree(n) == 0 and n in self._events
        ]

    # ── Depth & topology ──────────────────────────────────────────────────────

    def depth(self, event_id: str) -> int:
        """Depth of event in DAG (root = 0)."""
        par = self.parent(event_id)
        if par is None:
            return 0
        return 1 + self.depth(par.id)

    def topological_order(self) -> list[ClinicalEvent]:
        """Events in topological order (parents before children)."""
        return [
            self._events[n]
            for n in nx.topological_sort(self._g)
            if n in self._events
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Validate all AION §8.1 invariants.
        Returns list of error strings.
        """
        errors: list[str] = []

        # 1. Acyclicity (should always hold, but verify)
        if not nx.is_directed_acyclic_graph(self._g):
            errors.append("DAG contains cycles — AION §8.1 violated")

        # 2. Temporal embedding for all edges
        for parent_id, child_id in self._g.edges:
            if parent_id not in self._events or child_id not in self._events:
                continue
            p = self._events[parent_id]
            c = self._events[child_id]
            if not holds(AllenRelation.DURING, c.tau, p.tau):
                errors.append(
                    f"Temporal: During({child_id}, {parent_id}) violated. "
                    f"Child {c.tau!r} not inside parent {p.tau!r}"
                )

        # 3. Type conformance
        for parent_id, child_id in self._g.edges:
            if parent_id not in self._events or child_id not in self._events:
                continue
            p = self._events[parent_id]
            c = self._events[child_id]
            if not self._h.composition_valid(p.type, c.type):
                errors.append(
                    f"Composition: type '{c.type}' not in comp('{p.type}')"
                )

        return errors

    @property
    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    # ── Introspection ─────────────────────────────────────────────────────────

    def event(self, event_id: str) -> Optional[ClinicalEvent]:
        return self._events.get(event_id)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[ClinicalEvent]:
        return iter(self._events.values())

    def __contains__(self, event_id: str) -> bool:
        return event_id in self._events

    @property
    def graph(self) -> nx.DiGraph:
        return self._g

    def __repr__(self) -> str:
        return (
            f"ProcessDAG(patient={self.patient_id!r}, stay={self.stay_id!r}, "
            f"events={len(self)}, edges={self._g.number_of_edges()})"
        )


# ── ProcessIndex ──────────────────────────────────────────────────────────────

class ProcessIndex:
    """
    Efficient lookup of ProcessDAGs across all patients and stays.
    Maintains one DAG per (patient_id, stay_id) pair.
    """

    def __init__(self, hierarchy: Optional[TypeHierarchy] = None) -> None:
        self._h     = hierarchy or default_hierarchy()
        self._dags: dict[tuple[str, str], ProcessDAG] = {}

    def get_or_create(self, patient_id: str, stay_id: str) -> ProcessDAG:
        key = (patient_id, stay_id)
        if key not in self._dags:
            self._dags[key] = ProcessDAG(patient_id, stay_id, self._h)
        return self._dags[key]

    def get(self, patient_id: str, stay_id: str) -> Optional[ProcessDAG]:
        return self._dags.get((patient_id, stay_id))

    def all_dags(self) -> list[ProcessDAG]:
        return list(self._dags.values())

    def for_patient(self, patient_id: str) -> list[ProcessDAG]:
        return [d for (p, _), d in self._dags.items() if p == patient_id]

    def validate_all(self) -> dict[tuple[str, str], list[str]]:
        """Validate all DAGs. Returns {(patient_id, stay_id) → errors}."""
        return {k: d.validate() for k, d in self._dags.items() if d.validate()}

    def __len__(self) -> int:
        return len(self._dags)

    def __repr__(self) -> str:
        return f"ProcessIndex({len(self)} DAGs)"


# ── Builder helpers ───────────────────────────────────────────────────────────

@dataclass
class ProcessEdge:
    """Declarative subprocess relation for batch construction."""
    parent_id: str
    child_id:  str


def build_dag(
    patient_id: str,
    stay_id:    str,
    events:     list[ClinicalEvent],
    edges:      list[ProcessEdge],
    hierarchy:  Optional[TypeHierarchy] = None,
    validate:   bool = True,
) -> ProcessDAG:
    """
    Build a ProcessDAG from a list of events and subprocess edges.

    All events must belong to (patient_id, stay_id).
    Raises ValueError on constraint violations if validate=True.
    """
    dag = ProcessDAG(patient_id, stay_id, hierarchy)
    for e in events:
        dag.add_event(e)
    for edge in edges:
        dag.add_subprocess(edge.parent_id, edge.child_id, validate=validate)
    return dag
