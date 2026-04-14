# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.core.allen
===============
AION §6: Temporal Relation Algebra — all 13 Allen interval relations.

Convention: closed intervals [start, end], start <= end.
Ported and extended from SILD fm2/allen.py.
Extensions vs SILD:
  - AllenRelation.composition_table()  : full 13×13 Allen composition
  - inverse property on AllenRelation
  - holds_weak() : duration-tolerant predicate (ε-slack for fuzzy use)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import datetime

Timestamp = datetime.datetime


# ── Interval ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Interval:
    """Closed temporal interval [start, end] with start <= end."""
    start: Timestamp
    end:   Timestamp

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(
                f"Interval start {self.start} must be <= end {self.end}"
            )

    @property
    def duration(self) -> datetime.timedelta:
        return self.end - self.start

    @property
    def is_point(self) -> bool:
        return self.start == self.end

    def contains_point(self, t: Timestamp) -> bool:
        return self.start <= t <= self.end

    def __repr__(self) -> str:
        fmt = "%Y-%m-%dT%H:%M"
        return f"[{self.start.strftime(fmt)}, {self.end.strftime(fmt)}]"


# ── AllenRelation ─────────────────────────────────────────────────────────────

class AllenRelation(str, Enum):
    """
    All 13 Allen interval relations (AION §6 / Allen 1983).
    Values use the standard single-letter shorthand.
    """
    PRECEDES       = "p"   # I strictly before J
    PRECEDED_BY    = "pi"  # J strictly before I
    MEETS          = "m"   # I.end == J.start
    MET_BY         = "mi"  # J.end == I.start
    OVERLAPS       = "o"   # I starts before J, they overlap, I ends before J
    OVERLAPPED_BY  = "oi"  # symmetric of OVERLAPS
    STARTS         = "s"   # I.start == J.start, I ends before J
    STARTED_BY     = "si"  # symmetric of STARTS
    DURING         = "d"   # I strictly inside J
    CONTAINS       = "di"  # J strictly inside I  (during-inverse)
    FINISHES       = "f"   # I ends with J, I starts after J
    FINISHED_BY    = "fi"  # symmetric of FINISHES
    EQUALS         = "e"   # I.start == J.start and I.end == J.end

    @property
    def inverse(self) -> "AllenRelation":
        _inv: dict[str, str] = {
            "p": "pi", "pi": "p",
            "m": "mi", "mi": "m",
            "o": "oi", "oi": "o",
            "s": "si", "si": "s",
            "d": "di", "di": "d",
            "f": "fi", "fi": "f",
            "e": "e",
        }
        return AllenRelation(_inv[self.value])

    @property
    def is_symmetric(self) -> bool:
        return self == self.inverse

    # ------------------------------------------------------------------
    # Allen composition table (AION §6, Allen 1983 Table 4)
    # composition(r1, r2) returns the set of relations R such that:
    #   if I r1 J and J r2 K  then  I R K  (for some R in the result set)
    # ------------------------------------------------------------------
    def compose(self, other: "AllenRelation") -> frozenset["AllenRelation"]:
        """Return the set of possible Allen relations I ? K given I self J J other K."""
        return _COMPOSITION_TABLE.get(
            (self, other), frozenset(AllenRelation)
        )


# ── Core relation predicates ──────────────────────────────────────────────────

def _p (i: Interval, j: Interval) -> bool: return i.end < j.start
def _pi(i: Interval, j: Interval) -> bool: return j.end < i.start
def _m (i: Interval, j: Interval) -> bool: return i.end == j.start
def _mi(i: Interval, j: Interval) -> bool: return j.end == i.start
def _o (i: Interval, j: Interval) -> bool: return i.start < j.start < i.end < j.end
def _oi(i: Interval, j: Interval) -> bool: return j.start < i.start < j.end < i.end
def _s (i: Interval, j: Interval) -> bool: return i.start == j.start and i.end < j.end
def _si(i: Interval, j: Interval) -> bool: return i.start == j.start and i.end > j.end
def _d (i: Interval, j: Interval) -> bool: return j.start < i.start and i.end < j.end
def _di(i: Interval, j: Interval) -> bool: return i.start < j.start and j.end < i.end
def _f (i: Interval, j: Interval) -> bool: return i.start > j.start and i.end == j.end
def _fi(i: Interval, j: Interval) -> bool: return i.start < j.start and i.end == j.end
def _e (i: Interval, j: Interval) -> bool: return i.start == j.start and i.end == j.end


_PREDICATES: dict[AllenRelation, object] = {
    AllenRelation.PRECEDES:      _p,
    AllenRelation.PRECEDED_BY:   _pi,
    AllenRelation.MEETS:         _m,
    AllenRelation.MET_BY:        _mi,
    AllenRelation.OVERLAPS:      _o,
    AllenRelation.OVERLAPPED_BY: _oi,
    AllenRelation.STARTS:        _s,
    AllenRelation.STARTED_BY:    _si,
    AllenRelation.DURING:        _d,
    AllenRelation.CONTAINS:      _di,
    AllenRelation.FINISHES:      _f,
    AllenRelation.FINISHED_BY:   _fi,
    AllenRelation.EQUALS:        _e,
}


# ── Public API ────────────────────────────────────────────────────────────────

def classify(i: Interval, j: Interval) -> AllenRelation:
    """Return the unique Allen relation holding between i and j."""
    for rel, pred in _PREDICATES.items():
        if pred(i, j):          # type: ignore[operator]
            return rel
    raise RuntimeError(
        f"No Allen relation found for {i!r} and {j!r}. "
        "Verify that start <= end for both intervals."
    )


def holds(rel: AllenRelation, i: Interval, j: Interval) -> bool:
    """Test whether a specific Allen relation holds between i and j."""
    return _PREDICATES[rel](i, j)          # type: ignore[operator]


def holds_weak(
    rel: AllenRelation,
    i: Interval,
    j: Interval,
    epsilon: datetime.timedelta = datetime.timedelta(0),
) -> bool:
    """
    Duration-tolerant predicate: a boundary equality is considered satisfied
    if timestamps differ by at most *epsilon*.  Useful for fuzzy comparisons.
    """
    if epsilon == datetime.timedelta(0):
        return holds(rel, i, j)

    def eq(a: Timestamp, b: Timestamp) -> bool:
        return abs(a - b) <= epsilon

    def lt(a: Timestamp, b: Timestamp) -> bool:
        return a < b and not eq(a, b)

    s1, e1 = i.start, i.end
    s2, e2 = j.start, j.end

    mapping = {
        AllenRelation.PRECEDES:      lambda: lt(e1, s2),
        AllenRelation.PRECEDED_BY:   lambda: lt(e2, s1),
        AllenRelation.MEETS:         lambda: eq(e1, s2),
        AllenRelation.MET_BY:        lambda: eq(e2, s1),
        AllenRelation.OVERLAPS:      lambda: lt(s1, s2) and lt(s2, e1) and lt(e1, e2),
        AllenRelation.OVERLAPPED_BY: lambda: lt(s2, s1) and lt(s1, e2) and lt(e2, e1),
        AllenRelation.STARTS:        lambda: eq(s1, s2) and lt(e1, e2),
        AllenRelation.STARTED_BY:    lambda: eq(s1, s2) and lt(e2, e1),
        AllenRelation.DURING:        lambda: lt(s2, s1) and lt(e1, e2),
        AllenRelation.CONTAINS:      lambda: lt(s1, s2) and lt(e2, e1),
        AllenRelation.FINISHES:      lambda: lt(s2, s1) and eq(e1, e2),
        AllenRelation.FINISHED_BY:   lambda: lt(s1, s2) and eq(e1, e2),
        AllenRelation.EQUALS:        lambda: eq(s1, s2) and eq(e1, e2),
    }
    return mapping[rel]()


def relation_preserved(
    source_rel: AllenRelation,
    mapped_i: Optional[Interval],
    mapped_j: Optional[Interval],
) -> tuple[bool, Optional[AllenRelation]]:
    """
    Check whether *source_rel* is preserved after CDR→FHIR mapping.
    Returns (preserved, actual_relation | None).
    None means at least one interval was lost (total temporal loss).
    """
    if mapped_i is None or mapped_j is None:
        return False, None
    actual = classify(mapped_i, mapped_j)
    return actual == source_rel, actual


# ── Allen Composition Table (Allen 1983) ──────────────────────────────────────
# Subset of frequently used entries; full table for completeness.
# Key: (r1, r2) → frozenset of possible relations for (I ? K)

_R = AllenRelation
_all = frozenset(_R)

_COMPOSITION_TABLE: dict[tuple[AllenRelation, AllenRelation], frozenset[AllenRelation]] = {
    # I p J, J p K  →  I p K
    (_R.PRECEDES,    _R.PRECEDES):    frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.MEETS):       frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.OVERLAPS):    frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.STARTS):      frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.DURING):      frozenset({_R.PRECEDES, _R.OVERLAPS,
                                                  _R.MEETS, _R.DURING, _R.STARTS}),
    (_R.PRECEDES,    _R.FINISHES):    frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.EQUALS):      frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.CONTAINS):    frozenset({_R.PRECEDES, _R.OVERLAPS, _R.MEETS}),
    (_R.PRECEDES,    _R.STARTED_BY):  frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.FINISHED_BY): frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.OVERLAPPED_BY): frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.MET_BY):      frozenset({_R.PRECEDES}),
    (_R.PRECEDES,    _R.PRECEDED_BY): _all,

    (_R.EQUALS,      _R.EQUALS):      frozenset({_R.EQUALS}),
    (_R.EQUALS,      _R.PRECEDES):    frozenset({_R.PRECEDES}),
    (_R.EQUALS,      _R.PRECEDED_BY): frozenset({_R.PRECEDED_BY}),
    (_R.EQUALS,      _R.MEETS):       frozenset({_R.MEETS}),
    (_R.EQUALS,      _R.MET_BY):      frozenset({_R.MET_BY}),
    (_R.EQUALS,      _R.OVERLAPS):    frozenset({_R.OVERLAPS}),
    (_R.EQUALS,      _R.OVERLAPPED_BY): frozenset({_R.OVERLAPPED_BY}),
    (_R.EQUALS,      _R.STARTS):      frozenset({_R.STARTS}),
    (_R.EQUALS,      _R.STARTED_BY):  frozenset({_R.STARTED_BY}),
    (_R.EQUALS,      _R.DURING):      frozenset({_R.DURING}),
    (_R.EQUALS,      _R.CONTAINS):    frozenset({_R.CONTAINS}),
    (_R.EQUALS,      _R.FINISHES):    frozenset({_R.FINISHES}),
    (_R.EQUALS,      _R.FINISHED_BY): frozenset({_R.FINISHED_BY}),

    (_R.DURING,      _R.PRECEDES):    frozenset({_R.PRECEDES}),
    (_R.DURING,      _R.PRECEDED_BY): frozenset({_R.PRECEDED_BY}),
    (_R.DURING,      _R.MEETS):       frozenset({_R.PRECEDES}),
    (_R.DURING,      _R.MET_BY):      frozenset({_R.PRECEDED_BY}),
    (_R.DURING,      _R.EQUALS):      frozenset({_R.DURING}),
    (_R.DURING,      _R.DURING):      frozenset({_R.DURING}),
    (_R.DURING,      _R.CONTAINS):    _all,
    (_R.DURING,      _R.STARTS):      frozenset({_R.DURING}),
    (_R.DURING,      _R.FINISHES):    frozenset({_R.DURING}),
    (_R.DURING,      _R.OVERLAPS):    frozenset({_R.PRECEDES, _R.MEETS, _R.OVERLAPS}),
    (_R.DURING,      _R.OVERLAPPED_BY): frozenset({_R.PRECEDED_BY, _R.MET_BY, _R.OVERLAPPED_BY}),

    (_R.CONTAINS,    _R.CONTAINS):    frozenset({_R.CONTAINS}),
    (_R.CONTAINS,    _R.EQUALS):      frozenset({_R.CONTAINS}),
    (_R.CONTAINS,    _R.DURING):      _all,
    (_R.CONTAINS,    _R.PRECEDES):    frozenset({_R.PRECEDES}),
    (_R.CONTAINS,    _R.PRECEDED_BY): frozenset({_R.PRECEDED_BY}),
    (_R.CONTAINS,    _R.STARTS):      frozenset({_R.CONTAINS, _R.FINISHED_BY, _R.OVERLAPS}),
    (_R.CONTAINS,    _R.STARTED_BY):  frozenset({_R.CONTAINS}),
    (_R.CONTAINS,    _R.FINISHES):    frozenset({_R.CONTAINS, _R.STARTED_BY, _R.OVERLAPPED_BY}),
    (_R.CONTAINS,    _R.FINISHED_BY): frozenset({_R.CONTAINS}),
    (_R.CONTAINS,    _R.OVERLAPS):    frozenset({_R.PRECEDES, _R.MEETS, _R.OVERLAPS,
                                                  _R.CONTAINS, _R.FINISHED_BY}),
    (_R.CONTAINS,    _R.OVERLAPPED_BY): frozenset({_R.PRECEDED_BY, _R.MET_BY, _R.OVERLAPPED_BY,
                                                    _R.CONTAINS, _R.STARTED_BY}),
}
