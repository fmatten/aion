# aion/explain/shapley.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
"""
Erklärbarkeit nach §22 des AION-Papers.
Stdlib-only.

Implementiert:
  §22.1  Erklaerbarkeitsoperator Expl_l: X x Y -> 2^E
  §22.2  Shapley-Attribution auf Ereignisebene
  §22.3  Minimale kontrafaktische Ereignisaenderung Delta*_cf
  §22.4  Suffiziente Erklaerung S*_suf
"""
from __future__ import annotations
import math, logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Any

log = logging.getLogger(__name__)


# ── §22.2 Shapley-Attribution ─────────────────────────────────────────────

@dataclass
class ShapleyResult:
    """Shapley-Werte auf Ereignisebene nach §22.2."""
    event_contributions: dict   # event_id -> phi_e
    top_events:          list   # nach |phi_e| sortiert
    phi_min:             float
    total_contribution:  float

    def explaining_events(self) -> list:
        """Erklaerende Ereignisse: {e | phi_e >= phi_min} (§22.1)."""
        return [e for e, v in self.event_contributions.items()
                if v >= self.phi_min]

    def to_dict(self) -> dict:
        return {
            "top_events": self.top_events[:5],
            "phi_min":    self.phi_min,
            "total_contribution": round(self.total_contribution, 6),
            "explaining_event_count": len(self.explaining_events()),
        }


def shapley_event_attribution(
    events:     list,
    feature_fn: Callable,
    model_fn:   Callable[[list], float],
    phi_min:    float = 0.05,
) -> ShapleyResult:
    """
    Shapley-Wert phi_e(pk) nach §22.2.

    phi_j(pk) = sum_{C subset {1..d}{j}} [|C|!(d-|C|-1)!/d!] *
                [f(Psi_{C+j}) - f(Psi_C)]

    phi_e = sum_{j: e in S_j} phi_j / |S_j|

    Args:
        events:     Liste von ClinicalEvents
        feature_fn: Ψ: [events] -> feature_vector (list of floats)
        model_fn:   f^(5)_theta: features -> [0,1] (Risikoschatzung)
        phi_min:    Relevanzschwelle
    """
    d = len(events)
    if d == 0:
        return ShapleyResult({}, [], phi_min, 0.0)

    # Shapley exakt (exponentiell, praktisch bis d~15)
    shapley = {i: 0.0 for i in range(d)}
    baseline = model_fn(feature_fn([]))

    for j in range(d):
        others = [i for i in range(d) if i != j]
        for size in range(len(others) + 1):
            weight = (math.factorial(size) *
                      math.factorial(d - size - 1) /
                      math.factorial(d))
            for coalition in combinations(others, size):
                subset_with    = list(coalition) + [j]
                subset_without = list(coalition)
                v_with    = model_fn(feature_fn([events[i] for i in subset_with]))
                v_without = model_fn(feature_fn([events[i] for i in subset_without]))
                shapley[j] += weight * (v_with - v_without)

    # event_id -> Shapley-Wert
    contributions = {}
    for j, ev in enumerate(events):
        eid = getattr(ev, "event_id", None) or str(j)
        contributions[eid] = round(shapley[j], 6)

    top = sorted(contributions.items(), key=lambda x: -abs(x[1]))
    top_fmt = [{"event_id": k, "phi": v, "event_type": getattr(events[i], "event_type", "?")}
               for i, (k, v) in enumerate(top) if abs(v) >= phi_min]

    return ShapleyResult(
        event_contributions=contributions,
        top_events=top_fmt,
        phi_min=phi_min,
        total_contribution=sum(contributions.values()),
    )


# ── §22.3 Kontrafaktische Erklaerung ─────────────────────────────────────

@dataclass
class CounterfactualResult:
    """Minimale kontrafaktische Ereignisaenderung Delta*_cf nach §22.3."""
    changed_event_id:   str | None
    changed_attribute:  str | None
    original_value:     Any
    counterfactual_value: Any
    original_score:     float
    counterfactual_score: float
    delta_score:        float

    def to_dict(self) -> dict:
        return {
            "changed_event_id":     self.changed_event_id,
            "changed_attribute":    self.changed_attribute,
            "original_value":       self.original_value,
            "counterfactual_value": self.counterfactual_value,
            "original_score":       round(self.original_score, 4),
            "counterfactual_score": round(self.counterfactual_score, 4),
            "delta_score":          round(self.delta_score, 4),
            "interpretation": (
                f"Wenn {self.changed_attribute!r} "
                f"von {self.original_value} auf {self.counterfactual_value} "
                f"geaendert wuerde, sank das Risiko um "
                f"{abs(self.delta_score):.1%}."
            ),
        }


def minimal_counterfactual(
    events:     list,
    feature_fn: Callable,
    model_fn:   Callable[[list], float],
    target_reduction: float = 0.1,
) -> CounterfactualResult | None:
    """
    Minimale kontrafaktische Ereignisaenderung nach §22.3.

    Delta*_cf = argmin[Delta] |Delta| s.t. f(Psi(pk + Delta)) < r_hat - target

    Strategie: greedy - teste Attributveraenderungen einzelner Ereignisse.
    """
    import copy

    original_features = feature_fn(events)
    original_score    = model_fn(original_features)
    target_score      = original_score - target_reduction

    best = None

    for j, ev in enumerate(events):
        attrs = getattr(ev, "attributes", {}) or {}
        for attr, val in attrs.items():
            if not isinstance(val, (int, float)):
                continue
            # Teste Reduktion des Wertes auf verschiedene Prozentsaetze
            for factor in [0.5, 0.25, 0.1, 0.0]:
                new_val = val * factor
                modified = copy.copy(events[j])
                new_attrs = dict(attrs)
                new_attrs[attr] = new_val
                try:
                    object.__setattr__(modified, "attributes", new_attrs)
                except:
                    pass
                ev_list = events[:j] + [modified] + events[j+1:]
                new_score = model_fn(feature_fn(ev_list))
                if new_score <= target_score:
                    eid = getattr(ev, "event_id", None) or str(j)
                    best = CounterfactualResult(
                        changed_event_id=eid,
                        changed_attribute=attr,
                        original_value=val,
                        counterfactual_value=round(new_val, 4),
                        original_score=original_score,
                        counterfactual_score=new_score,
                        delta_score=new_score - original_score,
                    )
                    break
            if best:
                break
        if best:
            break

    return best


# ── §22.4 Suffiziente Erklaerung ─────────────────────────────────────────

@dataclass
class SufficientExplanation:
    """Suffiziente Erklaerung S*_suf nach §22.4."""
    sufficient_events: list
    full_score:        float
    restricted_score:  float
    epsilon_s:         float
    is_sufficient:     bool

    def to_dict(self) -> dict:
        return {
            "sufficient_event_ids": [
                getattr(e, "event_id", str(i))
                for i, e in enumerate(self.sufficient_events)
            ],
            "n_sufficient":    len(self.sufficient_events),
            "full_score":      round(self.full_score, 4),
            "restricted_score": round(self.restricted_score, 4),
            "is_sufficient":   self.is_sufficient,
        }


def sufficient_explanation(
    events:     list,
    feature_fn: Callable,
    model_fn:   Callable[[list], float],
    epsilon_s:  float = 0.05,
) -> SufficientExplanation:
    """
    Suffiziente Erklaerung nach §22.4.

    S*_suf = argmin S_suf subset E_pk |S|
             s.t. |f(Psi(pk|S)) - r_hat| <= epsilon_s

    Greedy: starte leer, fuege Ereignis mit groesstem Beitrag hinzu.
    """
    full_score = model_fn(feature_fn(events))
    selected   = []

    for _ in range(len(events)):
        remaining = [e for e in events if e not in selected]
        if not remaining:
            break
        # Ereignis mit groesstem Beitrag hinzufuegen
        best_e, best_score, best_delta = None, None, -1
        for ev in remaining:
            candidate = selected + [ev]
            score = model_fn(feature_fn(candidate))
            delta = abs(score - full_score)
            if best_e is None or delta < best_delta:
                best_e, best_score, best_delta = ev, score, delta
        selected.append(best_e)
        if abs(best_score - full_score) <= epsilon_s:
            return SufficientExplanation(
                sufficient_events=selected,
                full_score=full_score,
                restricted_score=best_score,
                epsilon_s=epsilon_s,
                is_sufficient=True,
            )

    final_score = model_fn(feature_fn(selected))
    return SufficientExplanation(
        sufficient_events=selected,
        full_score=full_score,
        restricted_score=final_score,
        epsilon_s=epsilon_s,
        is_sufficient=abs(final_score - full_score) <= epsilon_s,
    )


# ── §22.5 Beschränkte Erklärung Π⁺_l ──────────────────────────────────

@dataclass
class BoundedExplanation:
    """
    Beschränkte Erklärung nach §22.5.

    Π⁺_l: Erklärung mit |S| ≤ K_max.
    Wenn keine suffiziente Erklärung der Größe ≤ K_max existiert,
    wird die k-besten Ereignisse nach Shapley-Wert zurückgegeben.
    """
    selected_events:  list
    k_max:            int
    full_score:       float
    restricted_score: float
    epsilon_s:        float
    is_sufficient:    bool
    note:             str = ""

    def to_dict(self) -> dict:
        return {
            "selected_events": [
                {
                    "event_type": getattr(e, "event_type", "?"),
                    "t_start":    getattr(e, "t_start", "?").isoformat()
                                  if hasattr(getattr(e, "t_start", None), "isoformat")
                                  else str(getattr(e, "t_start", "?")),
                    "attributes": getattr(e, "attributes", {}),
                }
                for e in self.selected_events
            ],
            "k_max":            self.k_max,
            "actual_size":      len(self.selected_events),
            "full_score":       round(self.full_score, 4),
            "restricted_score": round(self.restricted_score, 4),
            "epsilon_s":        self.epsilon_s,
            "is_sufficient":    self.is_sufficient,
            "note":             self.note,
        }


def bounded_explanation(
    events:     list,
    feature_fn: Callable,
    model_fn:   Callable[[list], float],
    k_max:      int = 5,
    epsilon_s:  float = 0.05,
) -> BoundedExplanation:
    """
    Beschränkte Erklärung nach §22.5.

    Wenn |E_pk| ≤ k_max: gesamte Ereignismenge.
    Sonst: greedy bis k_max oder bis suffizient.

    Erfüllt Π⁺_l: |selected_events| ≤ k_max garantiert.
    """
    full_score = model_fn(feature_fn(events))

    # Wenn weniger Events als k_max: alle nehmen
    if len(events) <= k_max:
        return BoundedExplanation(
            selected_events=events,
            k_max=k_max,
            full_score=full_score,
            restricted_score=full_score,
            epsilon_s=epsilon_s,
            is_sufficient=True,
            note="Anzahl Ereignisse ≤ K_max – vollstaendige Erklaerung",
        )

    # Greedy-Auswahl, hart gekappt bei k_max
    selected = []
    is_sufficient = False
    restricted_score = full_score

    for step in range(k_max):
        remaining = [e for e in events if e not in selected]
        if not remaining:
            break
        best_e, best_score, best_delta = None, None, float("inf")
        for ev in remaining:
            candidate = selected + [ev]
            score = model_fn(feature_fn(candidate))
            delta = abs(score - full_score)
            if delta < best_delta:
                best_e, best_score, best_delta = ev, score, delta

        selected.append(best_e)
        restricted_score = best_score

        if abs(restricted_score - full_score) <= epsilon_s:
            is_sufficient = True
            break

    note = ("Suffiziente Erklaerung gefunden" if is_sufficient
            else f"Keine suffiziente Erklaerung mit |S| ≤ {k_max} "
                 f"(|f-f_S|={abs(restricted_score-full_score):.4f} > eps_s={epsilon_s})")

    return BoundedExplanation(
        selected_events=selected,
        k_max=k_max,
        full_score=full_score,
        restricted_score=restricted_score,
        epsilon_s=epsilon_s,
        is_sufficient=is_sufficient,
        note=note,
    )
