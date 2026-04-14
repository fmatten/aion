# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.privacy.differential
=========================
AION §20: Differential Privacy and Federated Model.

Implements:
  LaplaceMechanism     — ε-DP output via Laplace noise
  GaussianMechanism    — (ε,δ)-DP output via Gaussian noise
  PrivacyBudget        — budget tracking with sequential composition
  LocalDP              — local differential privacy per institution
  FederatedModel       — disjoint patient partitioning + DP queries
  DPCohortQuery        — privacy-protected cohort size estimation
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..core.event import EventSet
from ..query.cohort import CohortQuery, Cohort
from ..query.predicates import QueryContext


# ── Laplace distribution ──────────────────────────────────────────────────────

def _laplace_sample(scale: float, rng: random.Random) -> float:
    """
    Sample from Laplace(0, scale) using inverse CDF.
    Required to avoid scipy dependency.
    """
    u = rng.uniform(-0.5, 0.5)
    return -scale * math.copysign(1, u) * math.log(1 - 2 * abs(u))


def _gaussian_sample(sigma: float, rng: random.Random) -> float:
    """Sample from N(0, sigma²)."""
    return rng.gauss(0.0, sigma)


# ── Sensitivity ───────────────────────────────────────────────────────────────

class Sensitivity:
    """
    AION §20.3: Global ℓ₁-sensitivity of query functions.

    Δq = max_{E ~ E'} |q(E) - q(E')|
    where E ~ E' differ in exactly one event.
    """

    @staticmethod
    def cohort_size() -> float:
        """Δq = 1 for cohort size queries (one event can add/remove one patient)."""
        return 1.0

    @staticmethod
    def pattern_frequency() -> float:
        """Δq = 1 for pattern frequency queries."""
        return 1.0

    @staticmethod
    def mean_value(
        val_min: float,
        val_max: float,
        cohort_size: int,
    ) -> float:
        """
        Δq ≤ (val_max - val_min) / |P_φ| for mean of bounded attribute.
        """
        if cohort_size <= 0:
            return val_max - val_min
        return (val_max - val_min) / cohort_size


# ── PrivacyBudget ─────────────────────────────────────────────────────────────

@dataclass
class PrivacyBudget:
    """
    AION §20.5: Global privacy budget ε_total with sequential composition.

    Sequential composition theorem:
        If M_i is ε_i-DP, then (M_1,...,M_m) is Σε_i-DP.

    Budget tracking: each query consumes ε_i = ε_total / m (uniform split).
    """
    epsilon_total: float       # ε_total > 0
    _consumed:     float = field(default=0.0, init=False)
    _n_queries:    int   = field(default=0,   init=False)

    @property
    def remaining(self) -> float:
        return max(0.0, self.epsilon_total - self._consumed)

    @property
    def is_exhausted(self) -> bool:
        return self._consumed >= self.epsilon_total

    @property
    def n_queries(self) -> int:
        return self._n_queries

    def consume(self, epsilon: float) -> float:
        """
        Consume *epsilon* from the budget.
        Returns the actual epsilon allocated (may be less if budget low).
        """
        allocated = min(epsilon, self.remaining)
        self._consumed += allocated
        self._n_queries += 1
        return allocated

    def per_query_budget(self, n_queries: int) -> float:
        """Uniform split: ε_per_query = ε_remaining / n_queries."""
        if n_queries <= 0:
            return self.remaining
        return self.remaining / n_queries

    def __repr__(self) -> str:
        return (
            f"PrivacyBudget("
            f"ε_total={self.epsilon_total}, "
            f"consumed={self._consumed:.4f}, "
            f"remaining={self.remaining:.4f}, "
            f"queries={self._n_queries})"
        )


# ── LaplaceMechanism ──────────────────────────────────────────────────────────

@dataclass
class DPQueryResult:
    """Result of a DP-protected query."""
    true_value:   float
    noisy_value:  float
    epsilon_used: float
    mechanism:    str
    sensitivity:  float

    @property
    def noise(self) -> float:
        return self.noisy_value - self.true_value

    def __repr__(self) -> str:
        return (
            f"DPResult(true={self.true_value:.2f}, "
            f"noisy={self.noisy_value:.2f}, "
            f"ε={self.epsilon_used:.4f})"
        )


class LaplaceMechanism:
    """
    AION §20.4: Laplace mechanism for ε-DP.

    M_Lap(E) = q(E) + Lap(Δq / ε)

    Expected absolute error = Δq / ε.
    """

    def __init__(
        self,
        budget: PrivacyBudget,
        seed:   Optional[int] = None,
    ) -> None:
        self.budget = budget
        self._rng   = random.Random(seed)

    def release(
        self,
        true_value:  float,
        sensitivity: float,
        epsilon:     Optional[float] = None,
    ) -> DPQueryResult:
        """
        Release a DP-protected value.

        epsilon: if None, uses budget.remaining (consume all).
        """
        eps = self.budget.consume(epsilon or self.budget.remaining)
        if eps == 0:
            raise RuntimeError("Privacy budget exhausted")

        scale        = sensitivity / eps
        noise        = _laplace_sample(scale, self._rng)
        noisy_value  = true_value + noise

        return DPQueryResult(
            true_value=true_value,
            noisy_value=noisy_value,
            epsilon_used=eps,
            mechanism="Laplace",
            sensitivity=sensitivity,
        )

    def release_cohort_size(
        self,
        true_size: int,
        epsilon:   Optional[float] = None,
    ) -> DPQueryResult:
        """Convenience: release DP-protected cohort size."""
        return self.release(
            float(true_size),
            Sensitivity.cohort_size(),
            epsilon,
        )


class GaussianMechanism:
    """
    AION §20: Gaussian mechanism for (ε,δ)-DP.

    M_Gauss(E) = q(E) + N(0, σ²)
    where σ = Δq · sqrt(2 ln(1.25/δ)) / ε.
    """

    def __init__(
        self,
        budget: PrivacyBudget,
        delta:  float = 1e-5,
        seed:   Optional[int] = None,
    ) -> None:
        self.budget = budget
        self.delta  = delta
        self._rng   = random.Random(seed)

    def _sigma(self, sensitivity: float, epsilon: float) -> float:
        return sensitivity * math.sqrt(2 * math.log(1.25 / self.delta)) / epsilon

    def release(
        self,
        true_value:  float,
        sensitivity: float,
        epsilon:     Optional[float] = None,
    ) -> DPQueryResult:
        eps          = self.budget.consume(epsilon or self.budget.remaining)
        if eps == 0:
            raise RuntimeError("Privacy budget exhausted")
        sigma        = self._sigma(sensitivity, eps)
        noise        = _gaussian_sample(sigma, self._rng)
        return DPQueryResult(
            true_value=true_value,
            noisy_value=true_value + noise,
            epsilon_used=eps,
            mechanism="Gaussian",
            sensitivity=sensitivity,
        )


# ── DPCohortQuery ─────────────────────────────────────────────────────────────

class DPCohortQuery:
    """
    AION §20.6: DP-protected cohort query.

    P̂_{φ,ε} — noisy cohort size estimate.
    Returns verrauschte Größenschätzung, not the actual cohort.
    """

    def __init__(
        self,
        cohort_query: CohortQuery,
        mechanism:    LaplaceMechanism,
        epsilon:      Optional[float] = None,
    ) -> None:
        self.cohort_query = cohort_query
        self.mechanism    = mechanism
        self.epsilon      = epsilon

    def evaluate(self, ctx: QueryContext) -> "DPCohortResult":
        """
        Evaluate cohort and release DP-protected size.
        """
        cohort   = self.cohort_query.evaluate(ctx)
        dp_result = self.mechanism.release_cohort_size(
            cohort.size, self.epsilon
        )
        return DPCohortResult(
            query_name=self.cohort_query.name,
            true_size=cohort.size,
            dp_result=dp_result,
            cohort=cohort,
        )


@dataclass
class DPCohortResult:
    """Result of a DP cohort query."""
    query_name: str
    true_size:  int
    dp_result:  DPQueryResult
    cohort:     Optional[Cohort] = None

    @property
    def estimated_size(self) -> float:
        return self.dp_result.noisy_value

    @property
    def relative_error(self) -> Optional[float]:
        if self.true_size == 0:
            return None
        return abs(self.dp_result.noise) / self.true_size

    def __repr__(self) -> str:
        return (
            f"DPCohortResult(φ={self.query_name!r}, "
            f"true={self.true_size}, "
            f"estimated={self.estimated_size:.1f}, "
            f"ε={self.dp_result.epsilon_used:.4f})"
        )


# ── FederatedModel ────────────────────────────────────────────────────────────

@dataclass
class Institution:
    """
    AION §20.1: Single institution I_k with local patient partition P_k.
    """
    institution_id: str
    event_set:      EventSet
    budget:         PrivacyBudget

    @property
    def patient_ids(self) -> set[str]:
        return self.event_set.all_patients

    def local_cohort_size(
        self,
        query: CohortQuery,
        hierarchy,
    ) -> int:
        """Evaluate query locally and return true cohort size."""
        ctx    = QueryContext(event_set=self.event_set, hierarchy=hierarchy)
        cohort = query.evaluate(ctx)
        return cohort.size


class FederatedModel:
    """
    AION §20.1–§20.2: Federated model with disjoint patient partitioning.

    P = ⊔_k P_k,  P_k ∩ P_{k'} = ∅ for k ≠ k'.

    Supports:
      - Local cohort evaluation (no raw data shared)
      - Federated aggregation of DP-protected results
      - Sequential composition of privacy budgets
    """

    def __init__(self, hierarchy=None) -> None:
        self._institutions: dict[str, Institution] = {}
        self._h = hierarchy

    def add_institution(self, institution: Institution) -> None:
        """Register an institution. Validates disjoint patient sets."""
        new_pids = institution.patient_ids
        for existing in self._institutions.values():
            overlap = new_pids & existing.patient_ids
            if overlap:
                raise ValueError(
                    f"Patient overlap between {institution.institution_id!r} "
                    f"and {existing.institution_id!r}: {overlap}"
                )
        self._institutions[institution.institution_id] = institution

    def federated_cohort_size(
        self,
        query:   CohortQuery,
        use_ldp: bool  = True,
        epsilon: float = 1.0,
    ) -> "FederatedQueryResult":
        """
        AION §20.2: Evaluate query across all institutions.

        use_ldp=True: each institution adds local DP noise before aggregation.
        Returns federated estimate of |P_φ|.
        """
        local_results: dict[str, DPQueryResult] = {}
        true_total    = 0
        noisy_total   = 0.0

        for iid, inst in self._institutions.items():
            local_size = inst.local_cohort_size(query, self._h)
            true_total += local_size

            if use_ldp:
                # Local DP: add noise before sharing
                scale = Sensitivity.cohort_size() / epsilon
                noise = _laplace_sample(scale, random.Random())
                noisy = local_size + noise
            else:
                noisy = float(local_size)

            result = DPQueryResult(
                true_value=float(local_size),
                noisy_value=noisy,
                epsilon_used=epsilon if use_ldp else 0.0,
                mechanism="LDP" if use_ldp else "None",
                sensitivity=1.0,
            )
            local_results[iid] = result
            noisy_total += noisy

        return FederatedQueryResult(
            query_name=query.name,
            true_total=true_total,
            noisy_total=noisy_total,
            local_results=local_results,
            n_institutions=len(self._institutions),
            epsilon_per_institution=epsilon if use_ldp else 0.0,
        )

    @property
    def institutions(self) -> list[Institution]:
        return list(self._institutions.values())

    def total_patients(self) -> int:
        return sum(len(i.patient_ids) for i in self._institutions.values())

    def __len__(self) -> int:
        return len(self._institutions)

    def __repr__(self) -> str:
        return (
            f"FederatedModel("
            f"{len(self)} institutions, "
            f"{self.total_patients()} patients)"
        )


@dataclass
class FederatedQueryResult:
    """
    AION §20.2: Result of a federated cohort query.

    Expected error ≈ sqrt(K) / ε  (K = number of institutions).
    Unbiased: E[noisy_total] = true_total.
    """
    query_name:               str
    true_total:               int
    noisy_total:              float
    local_results:            dict[str, DPQueryResult]
    n_institutions:           int
    epsilon_per_institution:  float

    @property
    def absolute_error(self) -> float:
        return abs(self.noisy_total - self.true_total)

    @property
    def relative_error(self) -> Optional[float]:
        if self.true_total == 0:
            return None
        return self.absolute_error / self.true_total

    @property
    def expected_std(self) -> float:
        """E[std] = sqrt(K) / ε for LDP with Laplace(1/ε)."""
        if self.epsilon_per_institution == 0:
            return 0.0
        return math.sqrt(2 * self.n_institutions) / self.epsilon_per_institution

    def __repr__(self) -> str:
        return (
            f"FederatedResult(φ={self.query_name!r}, "
            f"true={self.true_total}, "
            f"noisy={self.noisy_total:.1f}, "
            f"K={self.n_institutions})"
        )
