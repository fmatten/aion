# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.query.predicates
=====================
AION §10.1: Atomic predicates of the formal query language.

All predicates operate on a QueryContext that bundles:
    event_set     : EventSet
    episode_index : EpisodeIndex
    process_index : ProcessIndex
    hierarchy     : TypeHierarchy

Atomic predicates (AION §10.1):
  Evt(p, a, τ, t^B, t^E, α)   — event existence
  HasType(e, τ)               — subtype test
  Attr(e, a_j, v)             — exact attribute check
  Val(e, a_j, θ)              — predicate on attribute value
  TRel(e1, e2, r)             — Allen relation between events
  SubOf(e1, e2)               — subprocess membership
  Episode(p, Φ, j, s, e)     — episode existence
  Dist(e1, e2, f, Δ_min, Δ_max) — temporal distance

Extended predicates (AION §10.2):
  Exists(n, pred)             — counting quantifier ≥ n
  Agg(events, q, agg, θ)     — aggregate condition
  HasPattern(p, π)            — RTP pattern match (delegates to patterns.py)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

from ..core.allen import AllenRelation, holds, Interval
from ..core.event import ClinicalEvent, EventSet
from ..core.process import ProcessIndex
from ..core.types import TypeHierarchy, default_hierarchy
from ..abstraction.episode import EpisodeIndex, Episode

if TYPE_CHECKING:
    from .patterns import RTPPattern


# ── QueryContext ──────────────────────────────────────────────────────────────

@dataclass
class QueryContext:
    """
    AION §10: S = (P, A, E, T, H_T, G, Q)
    Bundles all model components needed to evaluate predicates.
    """
    event_set:     EventSet
    episode_index: EpisodeIndex         = field(default_factory=EpisodeIndex)
    process_index: ProcessIndex         = field(default_factory=ProcessIndex)
    hierarchy:     TypeHierarchy        = field(default_factory=default_hierarchy)
    stay_intervals: dict[str, Interval] = field(default_factory=dict)
    # stay_intervals: {stay_id → Interval}

    def events_for(self, patient_id: str) -> list[ClinicalEvent]:
        return self.event_set.by_patient(patient_id)

    def all_patients(self) -> set[str]:
        return self.event_set.all_patients


# ── Distance function types ───────────────────────────────────────────────────

class DistFunc(str, Enum):
    START_TO_START  = "start"         # δ_start(e1,e2) = t^B(e2) - t^B(e1)
    END_TO_START    = "end_start"     # δ_end_start    = t^B(e2) - t^E(e1)
    GAP             = "gap"           # δ_gap          = max(0, t^B(e2)-t^E(e1))


def _compute_dist(
    f:  DistFunc,
    e1: ClinicalEvent,
    e2: ClinicalEvent,
) -> float:
    """Compute temporal distance in seconds."""
    s1, e1e = e1.tau.start, e1.tau.end
    s2      = e2.tau.start

    if f == DistFunc.START_TO_START:
        return (s2 - s1).total_seconds()
    elif f == DistFunc.END_TO_START:
        return (s2 - e1e).total_seconds()
    else:  # GAP
        raw = (s2 - e1e).total_seconds()
        return max(0.0, raw)


# ── Atomic Predicate Base ──────────────────────────────────────────────────────

class Predicate:
    """Base class for all AION query predicates."""

    def evaluate(self, ctx: QueryContext) -> bool:
        raise NotImplementedError

    def __and__(self, other: "Predicate") -> "AndPred":
        return AndPred(self, other)

    def __or__(self, other: "Predicate") -> "OrPred":
        return OrPred(self, other)

    def __invert__(self) -> "NotPred":
        return NotPred(self)


# ── Boolean combinators ───────────────────────────────────────────────────────

@dataclass
class AndPred(Predicate):
    left:  Predicate
    right: Predicate

    def evaluate(self, ctx: QueryContext) -> bool:
        return self.left.evaluate(ctx) and self.right.evaluate(ctx)


@dataclass
class OrPred(Predicate):
    left:  Predicate
    right: Predicate

    def evaluate(self, ctx: QueryContext) -> bool:
        return self.left.evaluate(ctx) or self.right.evaluate(ctx)


@dataclass
class NotPred(Predicate):
    inner: Predicate

    def evaluate(self, ctx: QueryContext) -> bool:
        return not self.inner.evaluate(ctx)


# ── Event-level predicates ─────────────────────────────────────────────────────

@dataclass
class HasType(Predicate):
    """
    AION §10.1: HasType(e, τ) ⟺ type(e) ≺* τ  (subtype test).
    """
    event: ClinicalEvent
    type_name: str

    def evaluate(self, ctx: QueryContext) -> bool:
        return ctx.hierarchy.is_subtype(self.event.type, self.type_name)


@dataclass
class AttrEq(Predicate):
    """
    AION §10.1: Attr(e, a_j, v) ⟺ α(e)(a_j) = v.
    """
    event:      ClinicalEvent
    attr_name:  str
    value:      Any

    def evaluate(self, ctx: QueryContext) -> bool:
        return self.event.attr(self.attr_name) == self.value


@dataclass
class AttrVal(Predicate):
    """
    AION §10.1: Val(e, a_j, θ) ⟺ θ(α(e)(a_j)).
    θ is any callable returning bool.
    """
    event:      ClinicalEvent
    attr_name:  str
    predicate:  Callable[[Any], bool]

    def evaluate(self, ctx: QueryContext) -> bool:
        v = self.event.attr(self.attr_name)
        if v is None:
            return False
        return self.predicate(v)


@dataclass
class TRel(Predicate):
    """
    AION §10.1: TRel(e1, e2, r) — Allen relation r between events.
    """
    e1:       ClinicalEvent
    e2:       ClinicalEvent
    relation: AllenRelation

    def evaluate(self, ctx: QueryContext) -> bool:
        return holds(self.relation, self.e1.tau, self.e2.tau)


@dataclass
class SubOf(Predicate):
    """
    AION §10.1: SubOf(e1, e2) ⟺ e2 →* e1 (e1 is in desc(e2)).
    """
    child_event_id:  str
    parent_event_id: str

    def evaluate(self, ctx: QueryContext) -> bool:
        # Find which DAG contains these events
        for dag in ctx.process_index.all_dags():
            if (self.child_event_id in dag
                    and self.parent_event_id in dag):
                desc_ids = {e.id for e in dag.desc(self.parent_event_id)}
                return self.child_event_id in desc_ids
        return False


@dataclass
class Dist(Predicate):
    """
    AION §10.1: Dist(e1, e2, f, Δ_min, Δ_max).
    Δ_min, Δ_max in seconds.
    """
    e1:       ClinicalEvent
    e2:       ClinicalEvent
    func:     DistFunc
    delta_min: float
    delta_max: float

    def evaluate(self, ctx: QueryContext) -> bool:
        d = _compute_dist(self.func, self.e1, self.e2)
        return self.delta_min <= d <= self.delta_max


@dataclass
class EpisodePred(Predicate):
    """
    AION §10.1: Episode(p, Φ, j, s, e) — j-th Φ-episode of p in [s,e].
    """
    patient_id: str
    type_set:   frozenset[str]
    index:      int             # 1-based; 0 = any episode
    interval:   Optional[Interval] = None   # [s, e] to check containment

    def evaluate(self, ctx: QueryContext) -> bool:
        eps = ctx.episode_index.get(
            self.patient_id, self.type_set,
            index=self.index if self.index > 0 else None,
        )
        if not eps:
            return False
        if self.interval is None:
            return True
        # Check that at least one episode overlaps [s, e]
        return any(
            ep.interval.start <= self.interval.end
            and ep.interval.end >= self.interval.start
            for ep in eps
        )


# ── Patient-level predicates (return set of events/episodes) ──────────────────

@dataclass
class EvtExists(Predicate):
    """
    AION §10.1: ∃ e ∈ E_p : φ(e).
    Evaluates *event_pred* against all events of *patient_id*.
    """
    patient_id:  str
    event_pred:  Callable[[ClinicalEvent], bool]

    def evaluate(self, ctx: QueryContext) -> bool:
        return any(
            self.event_pred(e)
            for e in ctx.events_for(self.patient_id)
        )


@dataclass
class EvtExistsN(Predicate):
    """
    AION §10.2 Counting quantifier: ∃^{≥n} e ∈ E_p : φ(e).
    """
    patient_id: str
    event_pred: Callable[[ClinicalEvent], bool]
    n:          int = 1

    def evaluate(self, ctx: QueryContext) -> bool:
        count = sum(
            1 for e in ctx.events_for(self.patient_id)
            if self.event_pred(e)
        )
        return count >= self.n


@dataclass
class AggCond(Predicate):
    """
    AION §10.2: Agg(S, q, agg, θ).
    Computes aggregator *agg_fn* over attribute *attr_name* of events *event_ids*,
    then tests *cond_fn* on the result.
    """
    event_ids: list[str]         # IDs of events in S
    attr_name: str               # attribute to aggregate
    agg_fn:    Callable[[list], Any]    # aggregator: list → value
    cond_fn:   Callable[[Any], bool]   # θ: value → bool

    def evaluate(self, ctx: QueryContext) -> bool:
        values = []
        for eid in self.event_ids:
            e = ctx.event_set.get(eid)
            if e is None:
                continue
            v = e.attr(self.attr_name)
            if v is not None:
                values.append(v)
        if not values:
            return False
        agg = self.agg_fn(values)
        return self.cond_fn(agg)


# ── Standard aggregator functions ─────────────────────────────────────────────

def agg_mean(values: list) -> float:
    return sum(values) / len(values)

def agg_max(values: list):
    return max(values)

def agg_min(values: list):
    return min(values)

def agg_count(values: list) -> int:
    return len(values)

def agg_sum(values: list):
    return sum(values)


# ── Convenience constructors ──────────────────────────────────────────────────

def evt_has_type(
    event: ClinicalEvent,
    type_name: str,
    ctx: QueryContext,
) -> bool:
    return ctx.hierarchy.is_subtype(event.type, type_name)


def evt_attr_gt(attr: str, threshold: float) -> Callable[[ClinicalEvent], bool]:
    return lambda e: (e.attr(attr) or 0) > threshold


def evt_attr_lt(attr: str, threshold: float) -> Callable[[ClinicalEvent], bool]:
    return lambda e: (e.attr(attr) or float("inf")) < threshold


def evt_attr_eq(attr: str, value: Any) -> Callable[[ClinicalEvent], bool]:
    return lambda e: e.attr(attr) == value


def evt_type_is(type_name: str, ctx: QueryContext) -> Callable[[ClinicalEvent], bool]:
    return lambda e: ctx.hierarchy.is_subtype(e.type, type_name)


def dist_seconds(
    e1: ClinicalEvent,
    e2: ClinicalEvent,
    func: DistFunc = DistFunc.START_TO_START,
) -> float:
    return _compute_dist(func, e1, e2)
