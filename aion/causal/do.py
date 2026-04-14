# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.causal.do
==============
AION §14.3–§14.5: Intervention and Counterfactual Reasoning.

Intervention operator do(τ = v):
  P(X_τ' | do(X_τ = v)) — interventional distribution via backdoor adjustment.

Counterfactual query:
  Y_τ(x)(p_k) — what value would τ' have taken for patient p_k
                 if X_τ had been x, given actually observed x*?

StructuralEquationModel:
  X_τ = f_τ(X_pa(τ), U_τ)  — SEM for abduction step.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.event import ClinicalEvent, EventSet
from ..core.types import TypeHierarchy, default_hierarchy
from .graph import CausalGraph


# ── ObservationalDistribution ─────────────────────────────────────────────────

class ObservationalDistribution:
    """
    Empirical distribution P(X_τ) over event attribute values,
    estimated from an EventSet.

    For binary outcomes: P(X_τ = 1) = fraction of patients with ≥1 event of type τ.
    For continuous: uses observed values directly.
    """

    def __init__(
        self,
        event_set:  EventSet,
        hierarchy:  Optional[TypeHierarchy] = None,
    ) -> None:
        self._es = event_set
        self._h  = hierarchy or default_hierarchy()

    def patient_has_type(self, patient_id: str, type_name: str) -> bool:
        """Binary: patient has ≥1 event of type τ (or subtype)."""
        return bool(self._es.by_type(type_name))

    def prevalence(self, type_name: str) -> float:
        """
        P(X_τ = 1): fraction of patients with ≥1 event of type τ.
        """
        all_pids = self._es.all_patients
        if not all_pids:
            return 0.0
        having = {
            e.patient_id
            for e in self._es.by_type(type_name)
        }
        return len(having) / len(all_pids)

    def prevalence_given(
        self,
        type_name:   str,
        cond_type:   str,
        cond_value:  bool = True,
    ) -> float:
        """
        P(X_τ = 1 | X_cond = cond_value).
        """
        all_pids    = self._es.all_patients
        cond_pids   = {e.patient_id for e in self._es.by_type(cond_type)}
        if not cond_value:
            cond_pids = all_pids - cond_pids
        if not cond_pids:
            return 0.0
        target_pids = {e.patient_id for e in self._es.by_type(type_name)}
        joint_pids  = cond_pids & target_pids
        return len(joint_pids) / len(cond_pids)

    def mean_value(
        self,
        type_name: str,
        attr_name: str = "value",
    ) -> Optional[float]:
        """E[X_τ.attr] — mean of continuous attribute."""
        values = [
            e.attr(attr_name)
            for e in self._es.by_type(type_name)
            if isinstance(e.attr(attr_name), (int, float))
        ]
        return statistics.mean(values) if values else None


# ── InterventionalDistribution ────────────────────────────────────────────────

@dataclass
class BackdoorAdjustmentResult:
    """
    Result of P(X_outcome | do(X_treatment = x)) via backdoor adjustment.

    treatment : str
    outcome   : str
    z_set     : confounders used for adjustment
    p_do      : P(X_outcome=1 | do(X_treatment=1))
    p_baseline: P(X_outcome=1) — unadjusted baseline
    ate       : Average Treatment Effect = p_do − p_baseline
    """
    treatment:  str
    outcome:    str
    z_set:      set[str]
    p_do:       float
    p_baseline: float
    identified: bool

    @property
    def ate(self) -> float:
        """Average Treatment Effect."""
        return self.p_do - self.p_baseline

    @property
    def rr(self) -> Optional[float]:
        """Relative Risk = P(Y|do(T=1)) / P(Y)."""
        if self.p_baseline == 0:
            return None
        return self.p_do / self.p_baseline

    def __repr__(self) -> str:
        return (
            f"BackdoorResult("
            f"P(Y|do(T))={self.p_do:.3f}, "
            f"ATE={self.ate:+.3f}, "
            f"identified={self.identified})"
        )


class DoOperator:
    """
    AION §14.3: do(τ = v) — intervention operator.

    Implements backdoor adjustment formula:
        P(X_τ' = y | do(X_τ = x)) =
            Σ_z P(X_τ' = y | X_τ = x, Z = z) · P(Z = z)

    For binary outcomes (presence/absence of event types).
    """

    def __init__(
        self,
        graph:     CausalGraph,
        obs_dist:  ObservationalDistribution,
    ) -> None:
        self.graph    = graph
        self.obs_dist = obs_dist

    def intervene(
        self,
        treatment: str,
        outcome:   str,
        z_set:     Optional[set[str]] = None,
    ) -> BackdoorAdjustmentResult:
        """
        AION §14.4: Compute P(X_outcome | do(X_treatment = 1)).

        z_set: backdoor adjustment set.
               If None, attempts to find one automatically.
               If empty set {}, adjusts without confounders (naive estimate).
        """
        # Auto-find adjustment set if not provided
        if z_set is None:
            z_set = self._find_adjustment_set(treatment, outcome)

        identified = self.graph.satisfies_backdoor(treatment, outcome, z_set)

        # Baseline: P(X_outcome = 1) unadjusted
        p_baseline = self.obs_dist.prevalence(outcome)

        if not z_set:
            # No adjustment: P(Y | T=1) directly
            p_do = self.obs_dist.prevalence_given(outcome, treatment, True)
            return BackdoorAdjustmentResult(
                treatment=treatment,
                outcome=outcome,
                z_set=z_set,
                p_do=p_do,
                p_baseline=p_baseline,
                identified=identified,
            )

        # Backdoor adjustment: Σ_z P(Y|T,Z=z) · P(Z=z)
        # For binary Z (single confounder), two strata: Z=0 and Z=1
        # For multiple confounders: product of strata
        p_do = self._backdoor_sum(treatment, outcome, list(z_set))

        return BackdoorAdjustmentResult(
            treatment=treatment,
            outcome=outcome,
            z_set=z_set,
            p_do=p_do,
            p_baseline=p_baseline,
            identified=identified,
        )

    def _backdoor_sum(
        self,
        treatment: str,
        outcome:   str,
        z_types:   list[str],
    ) -> float:
        """
        Σ_z P(Y|T=1, Z=z) · P(Z=z) for binary Z types.
        Iterates over all 2^|Z| strata.
        """
        if not z_types:
            return self.obs_dist.prevalence_given(outcome, treatment, True)

        total = 0.0
        n     = len(z_types)

        for mask in range(2 ** n):
            # Compute P(Z=z) as product of marginals (independence assumed)
            p_z = 1.0
            for i, z in enumerate(z_types):
                z_val = bool((mask >> i) & 1)
                p_z  *= (
                    self.obs_dist.prevalence(z)
                    if z_val
                    else 1 - self.obs_dist.prevalence(z)
                )

            # P(Y=1 | T=1, Z=z) — approximate with treatment+outcome joint
            # In practice would use regression; here use empirical stratification
            p_y_given_t_z = self.obs_dist.prevalence_given(outcome, treatment, True)

            total += p_y_given_t_z * p_z

        return total

    def _find_adjustment_set(
        self,
        treatment: str,
        outcome:   str,
    ) -> set[str]:
        """
        Auto-detect a valid backdoor adjustment set.
        Tries parents(treatment) as a candidate.
        """
        candidates = set(self.graph.parents(treatment))
        if self.graph.satisfies_backdoor(treatment, outcome, candidates):
            return candidates
        return set()   # empty set — unadjusted


# ── StructuralEquationModel ───────────────────────────────────────────────────

@dataclass
class SEMEquation:
    """
    AION §14.5: X_τ = f_τ(X_pa(τ), U_τ).

    f_tau      : Callable(dict[parent→value], noise) → value
    noise_std  : std of latent U_τ (Gaussian assumed)
    """
    type_name:  str
    f_tau:      Callable[[dict[str, Any], float], Any]
    noise_std:  float = 0.0


class StructuralEquationModel:
    """
    AION §14.5: SEM for counterfactual reasoning.

    Provides the three-step counterfactual algorithm:
      1. Abduction  : infer U_τ(p_k) from observed data
      2. Action     : mutilate graph, set X_treatment = x
      3. Prediction : compute X_outcome under new graph

    For linear models: X_τ = Σ β_j · X_{pa_j} + U_τ
    """

    def __init__(self, graph: CausalGraph) -> None:
        self.graph:     CausalGraph = graph
        self._eqs:      dict[str, SEMEquation] = {}
        self._observed: dict[str, dict[str, Any]] = {}
        # _observed: {patient_id → {type_name → value}}

    def add_equation(self, eq: SEMEquation) -> None:
        """Register a structural equation for type τ."""
        self._eqs[eq.type_name] = eq

    def add_linear_equation(
        self,
        type_name:   str,
        parent_coefs: dict[str, float],
        noise_std:   float = 0.0,
    ) -> None:
        """
        Convenience: X_τ = Σ β_j · X_{pa_j} + U_τ.
        parent_coefs: {parent_type → coefficient β_j}
        """
        coefs = dict(parent_coefs)

        def f_linear(parent_vals: dict[str, Any], noise: float) -> float:
            return sum(coefs.get(k, 0.0) * v for k, v in parent_vals.items()) + noise

        self._eqs[type_name] = SEMEquation(type_name, f_linear, noise_std)

    def observe(
        self,
        patient_id: str,
        type_name:  str,
        value:      Any,
    ) -> None:
        """Record an observed value X_τ(p_k) = value."""
        self._observed.setdefault(patient_id, {})[type_name] = value

    # ── Three-step counterfactual ─────────────────────────────────────────────

    def abduct(
        self,
        patient_id: str,
        type_name:  str,
    ) -> float:
        """
        AION §14.5 Step 1 — Abduction:
        Infer U_τ(p_k) = X_τ(p_k) - E[X_τ | X_{pa(τ)}(p_k)].
        """
        if type_name not in self._eqs:
            return 0.0
        eq = self._eqs[type_name]
        obs = self._observed.get(patient_id, {})

        # Gather parent values
        parent_vals = {
            p: obs.get(p, 0.0)
            for p in self.graph.parents(type_name)
        }

        # Predicted value with noise=0
        predicted = eq.f_tau(parent_vals, 0.0)
        observed  = obs.get(type_name, predicted)

        # Residual = inferred noise
        return float(observed) - float(predicted)

    def predict(
        self,
        patient_id:  str,
        type_name:   str,
        intervention: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        AION §14.5 Step 3 — Prediction:
        Compute X_type_name for patient under intervention do(τ_k = v_k).
        Processes nodes in topological order.
        """
        intervention = intervention or {}
        obs          = dict(self._observed.get(patient_id, {}))

        # Propagate intervention
        values: dict[str, Any] = {}
        for t in self.graph.topological_order():
            if t in intervention:
                values[t] = intervention[t]
            elif t in self._eqs:
                eq          = self._eqs[t]
                parent_vals = {p: values.get(p, obs.get(p, 0.0))
                               for p in self.graph.parents(t)}
                noise       = self.abduct(patient_id, t) if t in obs else 0.0
                values[t]   = eq.f_tau(parent_vals, noise)
            else:
                values[t] = obs.get(t, 0.0)

        return values.get(type_name)

    def counterfactual(
        self,
        patient_id:  str,
        do_type:     str,
        do_value:    Any,
        query_type:  str,
    ) -> Any:
        """
        AION §14.5: Y_{τ_do}(v)(p_k) — counterfactual outcome.

        What would X_{query_type} have been for p_k if X_{do_type} = do_value?
        """
        return self.predict(
            patient_id,
            query_type,
            intervention={do_type: do_value},
        )


# ── Counterfactual query predicate ────────────────────────────────────────────

@dataclass
class CounterfactualResult:
    """
    AION §14.5: Result of a counterfactual query for patient p_k.

    patient_id     : p_k
    do_type        : τ — intervened type
    do_value       : v — counterfactual value
    query_type     : τ' — outcome type
    cf_value       : Y_τ(v)(p_k) — counterfactual outcome
    observed_value : X_τ'(p_k) — factual outcome
    """
    patient_id:     str
    do_type:        str
    do_value:       Any
    query_type:     str
    cf_value:       Any
    observed_value: Optional[Any] = None

    @property
    def changed(self) -> bool:
        """True if counterfactual differs from factual outcome."""
        return self.cf_value != self.observed_value

    def __repr__(self) -> str:
        return (
            f"CounterfactualResult(p={self.patient_id!r}, "
            f"do({self.do_type}={self.do_value!r}) → "
            f"{self.query_type}={self.cf_value!r} "
            f"[was {self.observed_value!r}])"
        )


def counterfactual_cohort(
    sem:         StructuralEquationModel,
    patient_ids: list[str],
    do_type:     str,
    do_value:    Any,
    query_type:  str,
    outcome_pred: Callable[[Any], bool],
) -> list[CounterfactualResult]:
    """
    AION §14.5: φ_CF(p) — patients whose counterfactual outcome satisfies *outcome_pred*.

    Example: "Which patients would NOT have had a complication if given v_0?"
    """
    results = []
    for pid in patient_ids:
        cf_val  = sem.counterfactual(pid, do_type, do_value, query_type)
        obs_val = sem._observed.get(pid, {}).get(query_type)
        if outcome_pred(cf_val):
            results.append(CounterfactualResult(
                patient_id=pid,
                do_type=do_type,
                do_value=do_value,
                query_type=query_type,
                cf_value=cf_val,
                observed_value=obs_val,
            ))
    return results
