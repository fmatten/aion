# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.query.cohort
=================
AION §10.2: Cohort algebra and patient-level query engine.

A patient cohort formula φ(p) defines:
    P_φ = { p ∈ P | S ⊨ φ(p) }

Cohort algebra:
    P_φ ∩ P_ψ = P_{φ ∧ ψ}
    P_φ ∪ P_ψ = P_{φ ∨ ψ}
    P_φ \ P_ψ = P_{φ ∧ ¬ψ}

A CohortQuery wraps a formula φ(patient_id, ctx) → bool
and evaluates it over the full patient set.

Standard queries (AION §10.3 Example Queries A–D):
  QueryA — examination sequence within a process
  QueryB — treatment pathway with temporal distance
  QueryC — recurring episode pattern
  QueryD — aggregate condition over a process group
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional, Any

from ..core.event import ClinicalEvent, EventSet
from ..core.allen import AllenRelation, holds
from ..core.types import TypeHierarchy, default_hierarchy
from ..abstraction.episode import EpisodeIndex, Episode
from ..core.process import ProcessIndex
from .predicates import (
    QueryContext, DistFunc, _compute_dist,
    agg_mean, agg_max, agg_min,
)


# ── PatientFormula ────────────────────────────────────────────────────────────

# A formula φ: patient_id × QueryContext → bool
PatientFormula = Callable[[str, QueryContext], bool]


# ── CohortQuery ───────────────────────────────────────────────────────────────

class CohortQuery:
    """
    AION §10.2: Evaluates φ(p) for all p ∈ P.
    Returns P_φ = { p ∈ P | φ(p) }.
    """

    def __init__(
        self,
        formula: PatientFormula,
        name:    str = "φ",
    ) -> None:
        self.formula = formula
        self.name    = name

    def evaluate(self, ctx: QueryContext) -> "Cohort":
        """Evaluate over all patients in ctx."""
        members = {
            pid
            for pid in ctx.all_patients()
            if self.formula(pid, ctx)
        }
        return Cohort(members=members, query=self, ctx=ctx)

    def __and__(self, other: "CohortQuery") -> "CohortQuery":
        """P_φ ∩ P_ψ = P_{φ ∧ ψ}"""
        return CohortQuery(
            formula=lambda p, ctx: (
                self.formula(p, ctx) and other.formula(p, ctx)
            ),
            name=f"({self.name} ∧ {other.name})",
        )

    def __or__(self, other: "CohortQuery") -> "CohortQuery":
        """P_φ ∪ P_ψ = P_{φ ∨ ψ}"""
        return CohortQuery(
            formula=lambda p, ctx: (
                self.formula(p, ctx) or other.formula(p, ctx)
            ),
            name=f"({self.name} ∨ {other.name})",
        )

    def __sub__(self, other: "CohortQuery") -> "CohortQuery":
        """P_φ \ P_ψ = P_{φ ∧ ¬ψ}"""
        return CohortQuery(
            formula=lambda p, ctx: (
                self.formula(p, ctx) and not other.formula(p, ctx)
            ),
            name=f"({self.name} \\ {other.name})",
        )

    def __invert__(self) -> "CohortQuery":
        """¬φ"""
        return CohortQuery(
            formula=lambda p, ctx: not self.formula(p, ctx),
            name=f"¬{self.name}",
        )

    def __repr__(self) -> str:
        return f"CohortQuery({self.name!r})"


# ── Cohort ────────────────────────────────────────────────────────────────────

@dataclass
class Cohort:
    """
    Result of evaluating a CohortQuery — P_φ as a set of patient IDs.
    Supports further algebra operations and statistics.
    """
    members: set[str]
    query:   Optional[CohortQuery] = None
    ctx:     Optional[QueryContext] = None

    @property
    def size(self) -> int:
        return len(self.members)

    def intersect(self, other: "Cohort") -> "Cohort":
        return Cohort(members=self.members & other.members)

    def union(self, other: "Cohort") -> "Cohort":
        return Cohort(members=self.members | other.members)

    def difference(self, other: "Cohort") -> "Cohort":
        return Cohort(members=self.members - other.members)

    def __and__(self, other: "Cohort") -> "Cohort":
        return self.intersect(other)

    def __or__(self, other: "Cohort") -> "Cohort":
        return self.union(other)

    def __sub__(self, other: "Cohort") -> "Cohort":
        return self.difference(other)

    def __contains__(self, patient_id: str) -> bool:
        return patient_id in self.members

    def __len__(self) -> int:
        return self.size

    def __iter__(self):
        return iter(self.members)

    def __repr__(self) -> str:
        name = self.query.name if self.query else "?"
        return f"Cohort(|P_φ|={self.size}, φ={name!r})"

    def events(self) -> list[ClinicalEvent]:
        """All events of cohort members (requires ctx)."""
        if self.ctx is None:
            raise RuntimeError("No QueryContext attached to cohort")
        result = []
        for pid in self.members:
            result.extend(self.ctx.events_for(pid))
        return result

    def aggregate(
        self,
        attr_name: str,
        type_name: Optional[str] = None,
        agg_fn: Callable = agg_mean,
    ) -> Optional[float]:
        """
        AION §10.2: Agg(S, q, agg, θ) — aggregate attr_name over cohort events.
        """
        if self.ctx is None:
            return None
        values = []
        for e in self.events():
            if type_name and not self.ctx.hierarchy.is_subtype(e.type, type_name):
                continue
            v = e.attr(attr_name)
            if isinstance(v, (int, float)):
                values.append(v)
        return agg_fn(values) if values else None


# ── Standard Query Builders (AION §10.3) ──────────────────────────────────────

def query_has_type_event(
    type_name: str,
    attr_filter: Optional[Callable[[ClinicalEvent], bool]] = None,
) -> CohortQuery:
    """
    P_φ = patients with at least one event of type τ (and optional filter).
    """
    def formula(pid: str, ctx: QueryContext) -> bool:
        for e in ctx.events_for(pid):
            if not ctx.hierarchy.is_subtype(e.type, type_name):
                continue
            if attr_filter and not attr_filter(e):
                continue
            return True
        return False

    return CohortQuery(formula, name=f"∃e:HasType({type_name!r})")


def query_event_sequence(
    type_a: str,
    type_b: str,
    relation: AllenRelation = AllenRelation.PRECEDES,
    same_stay: bool = False,
    attr_filter_a: Optional[Callable[[ClinicalEvent], bool]] = None,
    attr_filter_b: Optional[Callable[[ClinicalEvent], bool]] = None,
) -> CohortQuery:
    """
    AION §10.3 Example A / FM-1 §12:
    Patients with event of type_a in relation *relation* to event of type_b.

    Same_stay=True: both events must share the same stay_id.
    """
    def formula(pid: str, ctx: QueryContext) -> bool:
        evts = ctx.events_for(pid)
        a_evts = [
            e for e in evts
            if ctx.hierarchy.is_subtype(e.type, type_a)
            and (attr_filter_a is None or attr_filter_a(e))
        ]
        b_evts = [
            e for e in evts
            if ctx.hierarchy.is_subtype(e.type, type_b)
            and (attr_filter_b is None or attr_filter_b(e))
        ]
        for ea in a_evts:
            for eb in b_evts:
                if same_stay and ea.stay_id != eb.stay_id:
                    continue
                if holds(relation, ea.tau, eb.tau):
                    return True
        return False

    name = (
        f"∃(e_a:{type_a!r}) {relation.value} (e_b:{type_b!r})"
        + (" [same stay]" if same_stay else "")
    )
    return CohortQuery(formula, name=name)


def query_treatment_path(
    dx_type:    str,
    med_type:   str,
    op_type:    str,
    dx_to_med_max_days:  float = 14.0,
    med_to_op_max_days:  float = 30.0,
    dx_attr:    Optional[str] = None,
    dx_value:   Any           = None,
    op_attr:    Optional[str] = None,
    op_value:   Any           = None,
) -> CohortQuery:
    """
    AION §10.3 Example B:
    φ_B(p) ⟺ ∃ e_d, e_m, e_o :
        HasType(e_d, dx_type) ∧ Dist(e_d, e_m, δ_start, 0, 14d)
        ∧ HasType(e_m, med_type)
        ∧ HasType(e_o, op_type)  ∧ Dist(e_m, e_o, δ_start, 0, 30d)
    """
    dx_max_s  = dx_to_med_max_days  * 86400.0
    med_max_s = med_to_op_max_days  * 86400.0

    def formula(pid: str, ctx: QueryContext) -> bool:
        evts = ctx.events_for(pid)
        dx_evts = [
            e for e in evts
            if ctx.hierarchy.is_subtype(e.type, dx_type)
            and (dx_attr is None or e.attr(dx_attr) == dx_value)
        ]
        med_evts = [
            e for e in evts if ctx.hierarchy.is_subtype(e.type, med_type)
        ]
        op_evts = [
            e for e in evts
            if ctx.hierarchy.is_subtype(e.type, op_type)
            and (op_attr is None or e.attr(op_attr) == op_value)
        ]

        for ed in dx_evts:
            for em in med_evts:
                d_dm = _compute_dist(DistFunc.START_TO_START, ed, em)
                if not (0 <= d_dm <= dx_max_s):
                    continue
                for eo in op_evts:
                    d_mo = _compute_dist(DistFunc.START_TO_START, em, eo)
                    if 0 <= d_mo <= med_max_s:
                        return True
        return False

    return CohortQuery(
        formula,
        name=f"TreatPath({dx_type!r}→{med_type!r}→{op_type!r})",
    )


def query_recurring_episodes(
    type_set:  frozenset[str],
    min_count: int = 2,
    min_gap_days: float = 0.0,
) -> CohortQuery:
    """
    AION §10.3 Example C:
    φ_C(p) ⟺ ∃ j < j' : Episode(p, Φ, j, ...) ∧ Episode(p, Φ, j', ...)
              ∧ gap(ε_j, ε_{j'}) ≥ min_gap_days
    """
    min_gap_s = min_gap_days * 86400.0

    def formula(pid: str, ctx: QueryContext) -> bool:
        episodes = ctx.episode_index.get(pid, type_set)
        if len(episodes) < min_count:
            return False
        if min_gap_s <= 0:
            return True
        for i in range(len(episodes) - 1):
            gap = episodes[i].gap_to(episodes[i + 1]).total_seconds()
            if gap >= min_gap_s:
                return True
        return False

    return CohortQuery(
        formula,
        name=f"RecurringEpisode(Φ={set(type_set)}, n≥{min_count})",
    )


def query_agg_over_desc(
    process_type: str,
    attr_name:    str,
    obs_type:     str,
    agg_fn:       Callable = agg_mean,
    threshold:    float    = 0.0,
    above:        bool     = True,
) -> "EventCohortQuery":
    """
    AION §10.3 Example D:
    ψ_D(e_op) ⟺ HasType(e_op, process_type) ∧
                Agg({e ∈ desc(e_op) | HasType(e, obs_type)}, attr, agg, θ)
    Returns an EventCohortQuery operating on individual events.
    """
    def formula(e: ClinicalEvent, ctx: QueryContext) -> bool:
        if not ctx.hierarchy.is_subtype(e.type, process_type):
            return False
        dag = None
        for d in ctx.process_index.all_dags():
            if e.id in d:
                dag = d
                break
        if dag is None:
            return False
        desc_obs = [
            d for d in dag.desc(e.id)
            if ctx.hierarchy.is_subtype(d.type, obs_type)
        ]
        values = [
            d.attr(attr_name)
            for d in desc_obs
            if isinstance(d.attr(attr_name), (int, float))
        ]
        if not values:
            return False
        result = agg_fn(values)
        return result > threshold if above else result < threshold

    return EventCohortQuery(formula, name=f"Agg({process_type!r}→{obs_type!r}.{attr_name})")


# ── EventCohortQuery ──────────────────────────────────────────────────────────

class EventCohortQuery:
    """
    Cohort query on individual events: ψ(e) → bool.
    Returns the set of matching events.
    """

    def __init__(
        self,
        formula: Callable[[ClinicalEvent, QueryContext], bool],
        name:    str = "ψ",
    ) -> None:
        self.formula = formula
        self.name    = name

    def evaluate(self, ctx: QueryContext) -> list[ClinicalEvent]:
        return [
            e for e in ctx.event_set.all_events
            if self.formula(e, ctx)
        ]

    def to_patient_query(self) -> CohortQuery:
        """
        Convert to patient query:
        φ(p) ⟺ ∃ e of p : ψ(e)
        """
        event_formula = self.formula

        def patient_formula(pid: str, ctx: QueryContext) -> bool:
            return any(
                event_formula(e, ctx)
                for e in ctx.events_for(pid)
            )

        return CohortQuery(
            patient_formula,
            name=f"∃e:{self.name}",
        )

    def __repr__(self) -> str:
        return f"EventCohortQuery({self.name!r})"
