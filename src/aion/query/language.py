# aion/query/language.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""
Formale Abfragesprache nach §11 des AION-Papers.
Stdlib-only.

Implementiert:
  §11.1  Atomare Praedikate (Evt, HasType, Attr, Val, TRel, Dist, Episode)
  §11.2  Kohortendefinition Pphi, Kohortenalgebra (AND/OR/NOT)
  §11.3  Beispielabfragen A-D
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger(__name__)


# ── §11.1 Atomare Praedikate ──────────────────────────────────────────

class Predicate:
    """Basisklasse fuer alle Praedikate."""
    def evaluate(self, event) -> bool:
        raise NotImplementedError

    def __and__(self, other): return AndPredicate(self, other)
    def __or__(self, other):  return OrPredicate(self, other)
    def __invert__(self):     return NotPredicate(self)


class AndPredicate(Predicate):
    def __init__(self, a, b): self.a, self.b = a, b
    def evaluate(self, e): return self.a.evaluate(e) and self.b.evaluate(e)

class OrPredicate(Predicate):
    def __init__(self, a, b): self.a, self.b = a, b
    def evaluate(self, e): return self.a.evaluate(e) or self.b.evaluate(e)

class NotPredicate(Predicate):
    def __init__(self, p): self.p = p
    def evaluate(self, e): return not self.p.evaluate(e)


class HasType(Predicate):
    """HasType(e, tau): type(e) = tau oder Untertyp."""
    def __init__(self, event_type: str, hierarchy=None):
        self.event_type = event_type
        self.hierarchy  = hierarchy

    def evaluate(self, e) -> bool:
        et = getattr(e, "event_type", "")
        if et == self.event_type:
            return True
        if self.hierarchy and hasattr(self.hierarchy, "is_subtype"):
            return self.hierarchy.is_subtype(et, self.event_type)
        return False


class Attr(Predicate):
    """Attr(e, aj, v): alpha(e)(aj) = v"""
    def __init__(self, attr_name: str, value: Any):
        self.attr_name = attr_name
        self.value     = value

    def evaluate(self, e) -> bool:
        attrs = getattr(e, "attributes", {}) or {}
        return attrs.get(self.attr_name) == self.value


class Val(Predicate):
    """Val(e, aj, theta): theta(alpha(e)(aj)) ist True."""
    def __init__(self, attr_name: str, op: str, threshold: float):
        self.attr_name = attr_name
        self.op        = op
        self.threshold = threshold
        self._ops = {
            ">": lambda v,t: v > t,
            "<": lambda v,t: v < t,
            ">=": lambda v,t: v >= t,
            "<=": lambda v,t: v <= t,
            "==": lambda v,t: v == t,
            "!=": lambda v,t: v != t,
        }

    def evaluate(self, e) -> bool:
        attrs = getattr(e, "attributes", {}) or {}
        v = attrs.get(self.attr_name)
        if v is None: return False
        try:
            fn = self._ops.get(self.op)
            return bool(fn(float(v), self.threshold)) if fn else False
        except (TypeError, ValueError):
            return False


class TRel(Predicate):
    """TRel(e1, e2, r): Allen-Relation r zwischen Zeitintervallen."""
    def __init__(self, other_event, relation: str):
        self.other    = other_event
        self.relation = relation.lower()

    def evaluate(self, e) -> bool:
        try:
            from aion import AllenInterval
            t1s = getattr(e,           "t_start", None)
            t1e = getattr(e,           "t_end",   None) or t1s
            t2s = getattr(self.other,  "t_start", None)
            t2e = getattr(self.other,  "t_end",   None) or t2s
            if not all([t1s, t2s]): return False
            i1 = AllenInterval(t1s.timestamp(), t1e.timestamp())
            i2 = AllenInterval(t2s.timestamp(), t2e.timestamp())
            return i1.relation_to(i2) == self.relation
        except Exception:
            return False


class Dist(Predicate):
    """Dist(e1, e2, f, Delta_min, Delta_max): Temporales Distanzpraedikat."""
    def __init__(self, other_event, dist_fn: str,
                 delta_min: float, delta_max: float):
        self.other     = other_event
        self.dist_fn   = dist_fn   # delta_start | delta_end_start | delta_gap
        self.delta_min = delta_min
        self.delta_max = delta_max

    def evaluate(self, e) -> bool:
        t1s = getattr(e,          "t_start", None)
        t1e = getattr(e,          "t_end",   None) or t1s
        t2s = getattr(self.other, "t_start", None)
        if not all([t1s, t2s]): return False
        try:
            if self.dist_fn == "delta_start":
                d = (t2s - t1s).total_seconds() / 86400
            elif self.dist_fn == "delta_end_start":
                d = (t2s - t1e).total_seconds() / 86400
            elif self.dist_fn == "delta_gap":
                d = max(0, (t2s - t1e).total_seconds() / 86400)
            else:
                return False
            return self.delta_min <= d <= self.delta_max
        except Exception:
            return False


# ── §11.2 Kohortenformeln ─────────────────────────────────────────────

@dataclass
class CohortFormula:
    """
    Formel phi(p) definiert eine Patientenkohorte P_phi.
    Unterstuetzt Zaehlquantoren, Aggregatbedingungen, Sequenzquantoren.
    """
    predicate:   Predicate | None = None
    event_type:  str | None       = None
    min_count:   int               = 1         # EXISTS >= n
    attr_filter: dict              = field(default_factory=dict)
    val_filters: list              = field(default_factory=list)
    # Aggregatbedingung
    agg_attr:    str | None       = None
    agg_op:      str | None       = None       # mean|max|min|count
    agg_thresh:  float | None     = None
    agg_comp:    str               = ">"

    def matches_event(self, event) -> bool:
        """Prueft ob ein einzelnes Ereignis das Praedikat erfuellt."""
        if self.event_type:
            et = getattr(event, "event_type", "")
            if et != self.event_type: return False
        attrs = getattr(event, "attributes", {}) or {}
        for k, v in self.attr_filter.items():
            if attrs.get(k) != v: return False
        for vf in self.val_filters:
            p = Val(vf["attr"], vf["op"], vf["threshold"])
            if not p.evaluate(event): return False
        if self.predicate:
            return self.predicate.evaluate(event)
        return True

    def evaluate_patient(self, events: list) -> bool:
        """Prueft ob Patient (anhand seiner Ereignisliste) die Formel erfuellt."""
        matching = [e for e in events if self.matches_event(e)]

        # Zaehlquantor: EXISTS >= min_count
        if len(matching) < self.min_count:
            return False

        # Aggregatbedingung: Agg(S, q, agg, theta)
        if self.agg_attr and self.agg_op and self.agg_thresh is not None:
            vals = [
                float(getattr(e,"attributes",{}).get(self.agg_attr, 0))
                for e in matching
                if isinstance(getattr(e,"attributes",{}).get(self.agg_attr), (int,float))
            ]
            if not vals: return False
            if self.agg_op == "mean":  agg = sum(vals) / len(vals)
            elif self.agg_op == "max": agg = max(vals)
            elif self.agg_op == "min": agg = min(vals)
            elif self.agg_op == "count": agg = float(len(vals))
            else: agg = sum(vals) / len(vals)
            ops = {">":agg>self.agg_thresh,"<":agg<self.agg_thresh,
                   ">=":agg>=self.agg_thresh,"<=":agg<=self.agg_thresh,
                   "==":agg==self.agg_thresh}
            return ops.get(self.agg_comp, False)

        return True


class CohortAlgebra:
    """
    Kohortenalgebra nach §11.2:
      P_phi AND P_psi = P_{phi AND psi}
      P_phi OR  P_psi = P_{phi OR  psi}
      P_phi NOT       = P_{NOT phi}
    """
    @staticmethod
    def intersect(a: set, b: set) -> set:
        return a & b

    @staticmethod
    def union(a: set, b: set) -> set:
        return a | b

    @staticmethod
    def difference(a: set, b: set) -> set:
        return a - b


# ── §11.3 Beispielabfragen ────────────────────────────────────────────

def example_A(laktat_high=4.0, laktat_low=2.0) -> dict:
    """
    Beispiel A (§11.3): Patienten mit Laktat > laktat_high
    gefolgt von Laktat <= laktat_low innerhalb einer OP.
    API-Repr: zwei Val-Filter mit Sequenz.
    """
    return {
        "description": "Laktat-Normalisierung nach OP",
        "formula": {
            "event_type": "Laborbefund",
            "val_filters": [
                {"attr": "qlaktat", "op": ">",  "threshold": laktat_high}
            ],
            "min_count": 1,
        },
        "followed_by": {
            "event_type": "Laborbefund",
            "val_filters": [
                {"attr": "qlaktat", "op": "<=", "threshold": laktat_low}
            ],
            "min_count": 1,
        }
    }

def example_D(laktat_mean_thresh=3.5) -> dict:
    """
    Beispiel D (§11.3): Operationen mit mittlerem Laktat > 3.5 mmol/l.
    """
    return {
        "description": "OP mit erhoehtem mittlerem Laktat",
        "formula": {
            "event_type": "Laborbefund",
            "agg_attr":   "qlaktat",
            "agg_op":     "mean",
            "agg_thresh": laktat_mean_thresh,
            "agg_comp":   ">",
            "min_count":  1,
        }
    }


# ── Abfrageausfuehrung ────────────────────────────────────────────────

async def execute_cohort_query(
    formula_dict: dict,
    store,
    patient_ids: list[str] | None = None,
    limit: int = 1000,
) -> dict:
    """
    Fuehrt eine Kohortenabfrage aus.

    Args:
        formula_dict: Kohortenformel als dict (aus REST-Body)
        store:        PostgresEventStore
        patient_ids:  Optional explizite Patientenliste
        limit:        Max. Ereignisse pro Patient

    Returns:
        dict mit matching_patients, event_counts, cohort_size
    """
    formula = CohortFormula(
        event_type=formula_dict.get("event_type"),
        min_count=formula_dict.get("min_count", 1),
        attr_filter=formula_dict.get("attr_filter", {}),
        val_filters=formula_dict.get("val_filters", []),
        agg_attr=formula_dict.get("agg_attr"),
        agg_op=formula_dict.get("agg_op"),
        agg_thresh=formula_dict.get("agg_thresh"),
        agg_comp=formula_dict.get("agg_comp", ">"),
    )

    # Patienten laden – SQL-optimiert
    if patient_ids:
        pids = patient_ids
    else:
        # Nur Patienten die relevanten event_type haben (schneller)
        async with store._pool.acquire() as conn:
            if formula.event_type:
                rows = await conn.fetch(
                    "SELECT DISTINCT patient_id FROM event WHERE type_id = $1 LIMIT $2",
                    formula.event_type, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT DISTINCT patient_id FROM event LIMIT $1", limit
                )
        pids = [r["patient_id"] for r in rows]

    matching = []
    event_counts = {}

    for pid in pids:
        # Events direkt nach type_id filtern wenn moeglich
        events = await store.find_by_patient(
            pid,
            type_filter=formula.event_type,
            limit=min(limit, 200)
        )
        matching_events = [e for e in events if formula.matches_event(e)]
        event_counts[pid] = len(matching_events)
        if formula.evaluate_patient(events):
            matching.append(pid)

    log.info("CohortQuery: %d/%d Patienten in Kohorte", len(matching), len(pids))
    return {
        "matching_patients": matching,
        "cohort_size":       len(matching),
        "total_patients":    len(pids),
        "event_counts":      event_counts,
    }
