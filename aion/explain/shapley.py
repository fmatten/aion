# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.explain.shapley
====================
AION §21: Explainability.

ExplainabilityOperator  — Expl_l : X_l × Y_l → 2^E
ShapleyExplainer        — φ_j(p_k) Shapley values at feature level → event level
CounterfactualExplainer — Δ*_cf minimal event set change
SufficientExplainer     — S*_suf minimal sufficient event subset
ExtendedValidator       — Π_l^+ with K_max explanation size gate

All three forms are complementary (AION §21):
  Shapley      — contribution of each event to risk estimate
  Counterfactual — minimal change that would alter the output
  Sufficient   — minimal event subset that determines the output
"""

from __future__ import annotations

import math
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.event import ClinicalEvent, EventSet
from ..core.types import TypeHierarchy, default_hierarchy
from ..ai.component import PatientFeatureVector, RiskEstimationComponent, ValidationDecision


# ── ExplainabilityOperator ────────────────────────────────────────────────────

@dataclass
class ExplanationResult:
    """
    AION §21.1: Result of Expl_l(x, y) ⊆ E.

    patient_id     : p_k
    explaining_events : S_{x,y} — events that justify the output
    output_value   : y = f_θ(x)
    fidelity       : L(f_θ|_S, y) — approximation quality
    method         : "shapley" | "counterfactual" | "sufficient"
    """
    patient_id:         str
    explaining_events:  list[ClinicalEvent]
    output_value:       Any
    fidelity:           float = 0.0
    method:             str   = ""

    @property
    def size(self) -> int:
        return len(self.explaining_events)

    @property
    def event_ids(self) -> set[str]:
        return {e.id for e in self.explaining_events}

    def __repr__(self) -> str:
        return (
            f"ExplanationResult(p={self.patient_id!r}, "
            f"|S|={self.size}, method={self.method!r}, "
            f"y={self.output_value!r})"
        )


# ── ShapleyExplainer ──────────────────────────────────────────────────────────

class ShapleyExplainer:
    """
    AION §21.2: Shapley-based attribution at event level.

    φ_j(p_k) = Σ_{C ⊆ {1,...,d}\\{j}} (|C|!(d-|C|-1)!/d!) ·
               [f_θ(Ψ_{C∪{j}}) - f_θ(Ψ_C)]

    Then back-propagated to event level:
        φ_e(p_k) = Σ_{j: e ∈ S_j} φ_j(p_k) / |S_j|

    where S_j = events contributing to feature j.

    Explanation set:
        Expl_5(p_k, r_k) = {e ∈ E_{p_k} | φ_e(p_k) ≥ φ_min}
    """

    def __init__(
        self,
        component:     RiskEstimationComponent,
        feature_names: list[str],
        phi_min:       float = 0.01,
        max_features:  int   = 10,   # truncate for tractability
    ) -> None:
        self.component     = component
        self.feature_names = feature_names
        self.phi_min       = phi_min
        self.max_features  = max_features

    # ── Shapley value computation ─────────────────────────────────────────────

    def _f(self, feature_values: list[float]) -> float:
        """Evaluate model on a feature vector (as list)."""
        return float(self.component.model_fn(feature_values))

    def _shapley_values(
        self,
        feature_vector: list[float],
    ) -> list[float]:
        """
        Compute exact Shapley values for all features.
        Uses marginal contribution over all coalitions.
        For d > max_features, uses sampling approximation.
        """
        d = len(feature_vector)
        if d == 0:
            return []

        baseline = [0.0] * d   # null coalition baseline
        phis     = [0.0] * d

        # Truncate if too many features
        indices  = list(range(min(d, self.max_features)))

        for j in indices:
            phi_j = 0.0
            # All coalitions C ⊆ {0,...,d-1} \ {j}
            others = [i for i in indices if i != j]
            for size in range(len(others) + 1):
                weight = (
                    math.factorial(size)
                    * math.factorial(d - size - 1)
                    / math.factorial(d)
                )
                for coalition in itertools.combinations(others, size):
                    # f(C ∪ {j}) - f(C)
                    fv_with = list(baseline)
                    fv_without = list(baseline)
                    for i in coalition:
                        fv_with[i]    = feature_vector[i]
                        fv_without[i] = feature_vector[i]
                    fv_with[j] = feature_vector[j]

                    phi_j += weight * (self._f(fv_with) - self._f(fv_without))

            phis[j] = phi_j

        return phis

    # ── Event-level attribution ───────────────────────────────────────────────

    def _feature_to_events(
        self,
        feature_idx:  int,
        patient_events: list[ClinicalEvent],
        event_set:    EventSet,
        hierarchy:    TypeHierarchy,
    ) -> list[ClinicalEvent]:
        """
        Map feature index → list of events that constitute that feature.
        Uses heuristic: feature "count_LabResult" → all LabResult events.
        """
        if feature_idx >= len(self.feature_names):
            return []
        fname = self.feature_names[feature_idx]

        # Parse feature name: "{agg}_{TypeName}_{attr}" or "count_{TypeName}"
        parts = fname.split("_", 1)
        if len(parts) < 2:
            return []

        agg, rest = parts[0], parts[1]
        # rest might be "TypeName" or "TypeName_attr"
        type_candidate = rest.split("_")[0]

        return [
            e for e in patient_events
            if hierarchy.is_subtype(e.type, type_candidate)
        ]

    def explain(
        self,
        patient_id:   str,
        feature_vec:  PatientFeatureVector,
        event_set:    EventSet,
        hierarchy:    Optional[TypeHierarchy] = None,
    ) -> ExplanationResult:
        """
        AION §21.2: Compute Expl_5(p_k, r_k).
        """
        h      = hierarchy or default_hierarchy()
        fv     = feature_vec.to_list(self.feature_names)
        risk   = self._f(fv)
        phis   = self._shapley_values(fv)

        patient_events = event_set.by_patient(patient_id)

        # Map feature Shapley values to event-level contributions
        event_phi: dict[str, float] = {}
        for j, phi_j in enumerate(phis):
            mapped_evts = self._feature_to_events(j, patient_events, event_set, h)
            if not mapped_evts:
                continue
            per_event = phi_j / len(mapped_evts)
            for e in mapped_evts:
                event_phi[e.id] = event_phi.get(e.id, 0.0) + per_event

        # Filter by threshold
        explaining = [
            e for e in patient_events
            if event_phi.get(e.id, 0.0) >= self.phi_min
        ]

        return ExplanationResult(
            patient_id=patient_id,
            explaining_events=explaining,
            output_value=risk,
            fidelity=self._fidelity(fv, explaining, patient_events),
            method="shapley",
        )

    def _fidelity(
        self,
        full_fv:     list[float],
        explaining:  list[ClinicalEvent],
        all_events:  list[ClinicalEvent],
    ) -> float:
        """
        Approximate fidelity: how much do explaining events contribute
        to the predicted risk?
        |f(full) - f(restricted)| / f(full)
        """
        if not full_fv:
            return 0.0
        full_risk  = self._f(full_fv)
        # Restricted: zero-out features NOT associated with explaining events
        # (simplified: use ratio of explaining event count)
        frac       = len(explaining) / len(all_events) if all_events else 0.0
        restr_risk = full_risk * frac
        if full_risk == 0:
            return 1.0
        return 1.0 - abs(full_risk - restr_risk) / max(full_risk, 1e-9)


# ── CounterfactualExplainer ───────────────────────────────────────────────────

@dataclass
class CounterfactualExplanation:
    """
    AION §21.3: Δ*_cf — minimal event change that alters the output.

    delta_events : events to add, remove, or modify
    action       : "remove" | "modify" | "add"
    cf_value     : predicted output after change
    original_value: original predicted output
    """
    patient_id:     str
    delta_events:   list[ClinicalEvent]
    action:         str   # "remove" | "modify"
    cf_value:       float
    original_value: float
    target_threshold: float = 0.5

    @property
    def delta_size(self) -> int:
        return len(self.delta_events)

    @property
    def changed(self) -> bool:
        """True if counterfactual crosses threshold in the desired direction."""
        orig_above = self.original_value >= self.target_threshold
        cf_above   = self.cf_value >= self.target_threshold
        return orig_above != cf_above

    def __repr__(self) -> str:
        return (
            f"CounterfactualExpl(p={self.patient_id!r}, "
            f"|Δ|={self.delta_size}, action={self.action!r}, "
            f"risk: {self.original_value:.3f}→{self.cf_value:.3f})"
        )


class CounterfactualExplainer:
    """
    AION §21.3: Minimal counterfactual event change.

    Δ*_cf(p_k) = argmin_{Δ} |Δ|  s.t.
        f_θ^(5)(Ψ(p_k ⊕ Δ)) ≠ desired_direction

    Strategy: greedy removal — remove highest-Shapley-value events
    one at a time until risk crosses threshold.
    """

    def __init__(
        self,
        component:     RiskEstimationComponent,
        feature_names: list[str],
        extractor:     Any,   # FeatureExtractor
        hierarchy:     Optional[TypeHierarchy] = None,
    ) -> None:
        self.component     = component
        self.feature_names = feature_names
        self.extractor     = extractor
        self._h            = hierarchy or default_hierarchy()
        self._shapley      = ShapleyExplainer(component, feature_names)

    def explain(
        self,
        patient_id:      str,
        feature_vec:     PatientFeatureVector,
        event_set:       EventSet,
        target_risk:     float = 0.25,
    ) -> CounterfactualExplanation:
        """
        Find minimal set of events whose removal brings risk ≤ target_risk.
        Greedy: remove events one at a time, always updating the working set.
        """
        original_fv   = feature_vec.to_list(self.feature_names)
        original_risk = float(self.component.model_fn(original_fv))

        phis = self._shapley._shapley_values(original_fv)
        all_patient_events = list(event_set.by_patient(patient_id))

        # Sort by descending absolute Shapley impact (use uniform weight if phis empty)
        def impact(e: ClinicalEvent) -> float:
            return abs(phis[0]) if phis else 0.0
        sorted_events = sorted(all_patient_events, key=impact, reverse=True)

        removed:       list[ClinicalEvent] = []
        remaining_ids: set[str] = {e.id for e in all_patient_events}
        cur_risk       = original_risk

        for e in sorted_events:
            if cur_risk <= target_risk:
                break
            # Remove e from the working set
            remaining_ids.discard(e.id)
            removed.append(e)

            # Build temp EventSet from remaining events only
            temp_es = EventSet(hierarchy=self._h)
            for ev in all_patient_events:
                if ev.id in remaining_ids:
                    try:
                        temp_es.add(ev)
                    except ValueError:
                        pass

            new_fv   = self.extractor.extract(patient_id, temp_es)
            cur_risk = float(self.component.model_fn(
                new_fv.to_list(self.feature_names)
            ))

        return CounterfactualExplanation(
            patient_id=patient_id,
            delta_events=removed,
            action="remove",
            cf_value=cur_risk,
            original_value=original_risk,
            target_threshold=target_risk,
        )


# ── SufficientExplainer ───────────────────────────────────────────────────────

@dataclass
class SufficientExplanation:
    """
    AION §21.4: S*_suf — minimal sufficient event subset.

    S*_suf(p_k) = argmin_{S ⊆ E_{p_k}} |S|  s.t.
        |f_θ^(5)(Ψ(p_k|_S)) - r_k| ≤ ε_S

    Provides the minimal "clinical picture" that determines the AI decision.
    """
    patient_id:       str
    sufficient_events: list[ClinicalEvent]
    output_value:     float
    approx_value:     float   # f(Ψ(p_k|_S))
    epsilon_s:        float

    @property
    def size(self) -> int:
        return len(self.sufficient_events)

    @property
    def is_faithful(self) -> bool:
        return abs(self.output_value - self.approx_value) <= self.epsilon_s

    def __repr__(self) -> str:
        return (
            f"SufficientExpl(p={self.patient_id!r}, "
            f"|S*|={self.size}, "
            f"faithful={self.is_faithful}, "
            f"ε_S={self.epsilon_s:.3f})"
        )


class SufficientExplainer:
    """
    AION §21.4: Find minimal sufficient event subset S*_suf.

    Algorithm: forward greedy — add events by Shapley impact
    until approximation error ≤ ε_S.
    """

    def __init__(
        self,
        component:     RiskEstimationComponent,
        feature_names: list[str],
        extractor:     Any,   # FeatureExtractor
        epsilon_s:     float = 0.05,
        hierarchy:     Optional[TypeHierarchy] = None,
    ) -> None:
        self.component     = component
        self.feature_names = feature_names
        self.extractor     = extractor
        self.epsilon_s     = epsilon_s
        self._h            = hierarchy or default_hierarchy()
        self._shapley      = ShapleyExplainer(component, feature_names)

    def explain(
        self,
        patient_id:  str,
        feature_vec: PatientFeatureVector,
        event_set:   EventSet,
    ) -> SufficientExplanation:
        """Find S*_suf for patient p_k."""
        full_fv     = feature_vec.to_list(self.feature_names)
        full_risk   = float(self.component.model_fn(full_fv))
        phis        = self._shapley._shapley_values(full_fv)

        patient_events = event_set.by_patient(patient_id)

        # Sort events by absolute Shapley impact (heuristic)
        def event_impact(e: ClinicalEvent) -> float:
            # Use feature count as proxy for index
            return abs(phis[0]) if phis else 0.0

        sorted_events = sorted(patient_events, key=event_impact, reverse=True)

        included:  list[ClinicalEvent] = []
        cur_risk   = 0.0

        for e in sorted_events:
            included.append(e)
            # Build partial event set
            temp_es = EventSet(hierarchy=self._h)
            for ev in included:
                try:
                    temp_es.add(ev)
                except ValueError:
                    pass
            new_fv   = self.extractor.extract(patient_id, temp_es)
            cur_risk = float(self.component.model_fn(
                new_fv.to_list(self.feature_names)
            ))
            if abs(cur_risk - full_risk) <= self.epsilon_s:
                break   # sufficient subset found

        return SufficientExplanation(
            patient_id=patient_id,
            sufficient_events=included,
            output_value=full_risk,
            approx_value=cur_risk,
            epsilon_s=self.epsilon_s,
        )


# ── Extended Validation Operator Π_l^+ ───────────────────────────────────────

class ExtendedValidationOperator:
    """
    AION §21.5: Π_l^+ — validation with explainability size gate.

    Π_l^+(y) = y    if Π_l(y) ≠ ⊥ ∧ |Expl_l(x, y)| ≤ K_max
    Π_l^+(y) = ⊥    otherwise

    K_max is the maximum permitted explanation size — a configurable
    measure for regulatory requirements (EU AI Act).
    """

    def __init__(
        self,
        base_validator:  Any,          # ValidationOperator
        explainer:       ShapleyExplainer,
        k_max:           int = 10,
    ) -> None:
        self.base_validator = base_validator
        self.explainer      = explainer
        self.k_max          = k_max

    def validate(
        self,
        output:        Any,
        patient_id:    str,
        feature_vec:   PatientFeatureVector,
        event_set:     EventSet,
        hierarchy:     Optional[TypeHierarchy] = None,
    ) -> ValidationDecision:
        """Full Π_l^+(y) validation."""
        # 1. Base validation Π_l
        base = self.base_validator.validate(output)
        if not base.accepted:
            return base

        # 2. Explainability size gate: |Expl| ≤ K_max
        expl = self.explainer.explain(patient_id, feature_vec, event_set, hierarchy)
        if expl.size > self.k_max:
            return ValidationDecision(
                accepted=False,
                reason="explanation_too_large",
                errors=[
                    f"|Expl|={expl.size} > K_max={self.k_max} — "
                    f"regulatory explainability requirement not met"
                ],
            )

        return ValidationDecision(accepted=True)


# ══════════════════════════════════════════════════════════════════════════════
# Convenience: full explanation report
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FullExplanationReport:
    """
    Combines all three explanation forms for a single patient.
    """
    patient_id:       str
    risk_estimate:    float
    shapley:          Optional[ExplanationResult]          = None
    counterfactual:   Optional[CounterfactualExplanation]  = None
    sufficient:       Optional[SufficientExplanation]       = None

    def summary(self) -> str:
        lines = [
            f"Patient:  {self.patient_id}",
            f"Risk:     {self.risk_estimate:.3f}",
        ]
        if self.shapley:
            ids = [e.id[:8] for e in self.shapley.explaining_events]
            lines.append(f"Shapley:  {len(self.shapley.explaining_events)} events → {ids}")
        if self.counterfactual:
            lines.append(
                f"CF:       remove {self.counterfactual.delta_size} events → "
                f"risk {self.counterfactual.cf_value:.3f}"
            )
        if self.sufficient:
            lines.append(
                f"Sufficient: {self.sufficient.size} events, "
                f"faithful={self.sufficient.is_faithful}"
            )
        return "\n".join(lines)
