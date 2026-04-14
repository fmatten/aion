# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.core.fuzzy
===============
AION §7: Fuzzy and Uncertain Time Intervals.

Extends the exact interval model with imprecision radii ε and
stochastic time intervals [T^B, T^E].

Key classes:
  FuzzyInterval       — I~ = ([t^B ± ε^B], [t^E ± ε^E])
  FuzzyEvent          — ClinicalEvent with FuzzyInterval instead of Interval
  ProbabilisticAllen  — P(I~_1 r I~_2) ∈ [0,1] for each Allen relation
  FuzzyQualityIndex   — Γ_temp(e~) = P([T^B,T^E] ⊆ stay)
  TemporalValidator   — Π_temp with configurable threshold γ_emb

All deterministic structures remain as special cases with ε = 0.
"""

from __future__ import annotations

import math
import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable

from .allen import AllenRelation, Interval, classify


# ── Normal CDF (no scipy dependency) ─────────────────────────────────────────

def _phi(x: float) -> float:
    """Standard normal CDF Φ(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── FuzzyInterval ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FuzzyInterval:
    """
    AION §7.1: Fuzzy time interval
        I~ = ([t^B - ε^B, t^B + ε^B], [t^E - ε^E, t^E + ε^E])

    nominal_start / nominal_end : t^B, t^E — nominal (best-estimate) timestamps
    eps_start / eps_end         : ε^B, ε^E — imprecision radii (seconds as float)

    Degenerate case: ε^B = ε^E = 0  →  exact Interval [t^B, t^E]
    """
    nominal_start: datetime.datetime
    nominal_end:   datetime.datetime
    eps_start:     float = 0.0   # ε^B in seconds
    eps_end:       float = 0.0   # ε^E in seconds

    def __post_init__(self) -> None:
        if self.nominal_start > self.nominal_end:
            raise ValueError(
                f"nominal_start {self.nominal_start} > nominal_end {self.nominal_end}"
            )
        if self.eps_start < 0 or self.eps_end < 0:
            raise ValueError("Imprecision radii must be >= 0")

    # ── Derived intervals ─────────────────────────────────────────────────────

    @property
    def sharp_core(self) -> Interval:
        """[t^B, t^E] — the nominal exact interval."""
        return Interval(self.nominal_start, self.nominal_end)

    @property
    def outer_hull(self) -> Interval:
        """[t^B - ε^B, t^E + ε^E] — widest possible interval."""
        return Interval(
            self.nominal_start - datetime.timedelta(seconds=self.eps_start),
            self.nominal_end   + datetime.timedelta(seconds=self.eps_end),
        )

    @property
    def is_exact(self) -> bool:
        return self.eps_start == 0.0 and self.eps_end == 0.0

    def to_exact(self) -> Interval:
        """Return sharp core; raises if not exact."""
        return self.sharp_core

    # ── Embedding probability ─────────────────────────────────────────────────

    def embedding_probability(self, stay: Interval) -> float:
        """
        AION §7.4: Γ_temp(I~) = P([T^B, T^E] ⊆ stay).
        Assumes independent normal distributions for T^B and T^E.
        Returns probability ∈ [0,1].
        """
        if self.is_exact:
            core = self.sharp_core
            return 1.0 if (core.start >= stay.start and core.end <= stay.end) else 0.0

        # P(T^B >= stay.start) * P(T^E <= stay.end)
        # T^B ~ N(nominal_start, eps_start^2) in seconds
        s_start = (self.nominal_start - stay.start).total_seconds()
        s_end   = (stay.end - self.nominal_end).total_seconds()

        p_start = _phi(s_start / self.eps_start) if self.eps_start > 0 else (1.0 if s_start >= 0 else 0.0)
        p_end   = _phi(s_end   / self.eps_end)   if self.eps_end   > 0 else (1.0 if s_end   >= 0 else 0.0)

        return p_start * p_end

    def __repr__(self) -> str:
        fmt = "%Y-%m-%dT%H:%M"
        return (
            f"FuzzyInterval("
            f"[{self.nominal_start.strftime(fmt)}±{self.eps_start:.0f}s, "
            f"{self.nominal_end.strftime(fmt)}±{self.eps_end:.0f}s])"
        )


# ── ProbabilisticAllen ────────────────────────────────────────────────────────

class ProbabilisticAllen:
    """
    AION §7.3: Probabilistic Allen relations for fuzzy intervals.

    P(I~_1 r I~_2) ∈ [0,1] — confidence that relation r holds.

    Uses the normal-distribution model:
        T_j^B ~ N(t_j^B, ε_j^B²)
        T_j^E ~ N(t_j^E, ε_j^E²)  (independent)

    For exact intervals (ε=0), all probabilities are 0 or 1.
    """

    @staticmethod
    def _sigma(eps_a: float, eps_b: float) -> float:
        """Combined std dev for difference of two normals."""
        return math.sqrt(eps_a ** 2 + eps_b ** 2)

    @staticmethod
    def _p_lt(mu_a: float, eps_a: float, mu_b: float, eps_b: float) -> float:
        """P(X_a < X_b) where X_a ~ N(mu_a, eps_a²), X_b ~ N(mu_b, eps_b²)."""
        sigma = ProbabilisticAllen._sigma(eps_a, eps_b)
        if sigma == 0.0:
            return 1.0 if mu_a < mu_b else (0.5 if mu_a == mu_b else 0.0)
        return _phi((mu_b - mu_a) / sigma)

    @staticmethod
    def _p_eq(mu_a: float, eps_a: float, mu_b: float, eps_b: float,
              tol: float = 1.0) -> float:
        """
        Approximate P(X_a ≈ X_b) — probability that |X_a - X_b| <= tol seconds.
        Uses normal CDF of the difference distribution.
        """
        sigma = ProbabilisticAllen._sigma(eps_a, eps_b)
        if sigma == 0.0:
            return 1.0 if abs(mu_a - mu_b) <= tol else 0.0
        diff = mu_a - mu_b
        return _phi((tol - diff) / sigma) - _phi((-tol - diff) / sigma)

    @classmethod
    def confidence(
        cls,
        rel:  AllenRelation,
        i:    FuzzyInterval,
        j:    FuzzyInterval,
        tol:  float = 1.0,   # seconds — boundary equality tolerance
    ) -> float:
        """
        AION §7.3: P(I~_i  r  I~_j) ∈ [0,1].
        *tol*: seconds within which two timestamps count as "equal".

        All times are converted to seconds since the earliest start for stability.
        """
        # Reference epoch
        t0 = min(i.nominal_start, j.nominal_start)

        def _s(ts: datetime.datetime) -> float:
            return (ts - t0).total_seconds()

        s1 = _s(i.nominal_start); e1 = _s(i.nominal_end)
        s2 = _s(j.nominal_start); e2 = _s(j.nominal_end)
        εs1, εe1 = i.eps_start, i.eps_end
        εs2, εe2 = j.eps_start, j.eps_end

        lt  = cls._p_lt
        eq  = lambda a, ea, b, eb: cls._p_eq(a, ea, b, eb, tol)

        # Deterministic shortcuts
        if i.is_exact and j.is_exact:
            actual = classify(i.sharp_core, j.sharp_core)
            return 1.0 if actual == rel else 0.0

        # ── All 13 Allen relations ────────────────────────────────────────────

        if rel == AllenRelation.PRECEDES:
            # P(E1 < S2)
            return lt(e1, εe1, s2, εs2)

        elif rel == AllenRelation.PRECEDED_BY:
            # P(E2 < S1)
            return lt(e2, εe2, s1, εs1)

        elif rel == AllenRelation.MEETS:
            # P(E1 = S2)
            return eq(e1, εe1, s2, εs2)

        elif rel == AllenRelation.MET_BY:
            # P(E2 = S1)
            return eq(e2, εe2, s1, εs1)

        elif rel == AllenRelation.EQUALS:
            # P(S1 = S2 and E1 = E2)
            return eq(s1, εs1, s2, εs2) * eq(e1, εe1, e2, εe2)

        elif rel == AllenRelation.STARTS:
            # P(S1 = S2 and E1 < E2)
            return eq(s1, εs1, s2, εs2) * lt(e1, εe1, e2, εe2)

        elif rel == AllenRelation.STARTED_BY:
            # P(S1 = S2 and E2 < E1)
            return eq(s1, εs1, s2, εs2) * lt(e2, εe2, e1, εe1)

        elif rel == AllenRelation.FINISHES:
            # P(E1 = E2 and S1 > S2)
            return eq(e1, εe1, e2, εe2) * lt(s2, εs2, s1, εs1)

        elif rel == AllenRelation.FINISHED_BY:
            # P(E1 = E2 and S2 > S1)
            return eq(e1, εe1, e2, εe2) * lt(s1, εs1, s2, εs2)

        elif rel == AllenRelation.DURING:
            # P(S2 < S1 and E1 < E2)
            return lt(s2, εs2, s1, εs1) * lt(e1, εe1, e2, εe2)

        elif rel == AllenRelation.CONTAINS:
            # P(S1 < S2 and E2 < E1)
            return lt(s1, εs1, s2, εs2) * lt(e2, εe2, e1, εe1)

        elif rel == AllenRelation.OVERLAPS:
            # P(S1 < S2 < E1 < E2)
            return (lt(s1, εs1, s2, εs2)
                    * lt(s2, εs2, e1, εe1)
                    * lt(e1, εe1, e2, εe2))

        elif rel == AllenRelation.OVERLAPPED_BY:
            # P(S2 < S1 < E2 < E1)
            return (lt(s2, εs2, s1, εs1)
                    * lt(s1, εs1, e2, εe2)
                    * lt(e2, εe2, e1, εe1))

        return 0.0   # unreachable

    @classmethod
    def all_confidences(
        cls,
        i: FuzzyInterval,
        j: FuzzyInterval,
        tol: float = 1.0,
    ) -> dict[AllenRelation, float]:
        """Return confidence for all 13 relations (sums to ~1 for exact intervals)."""
        return {
            r: cls.confidence(r, i, j, tol)
            for r in AllenRelation
        }

    @classmethod
    def most_likely(
        cls,
        i: FuzzyInterval,
        j: FuzzyInterval,
        tol: float = 1.0,
    ) -> tuple[AllenRelation, float]:
        """Return the most probable Allen relation and its confidence."""
        confs = cls.all_confidences(i, j, tol)
        best  = max(confs, key=confs.__getitem__)
        return best, confs[best]


# ── Probabilistic Temporal Predicate ─────────────────────────────────────────

@dataclass
class FuzzyTemporalPredicate:
    """
    AION §7.4: TRel~(e~_1, e~_2, r, γ) — probabilistic temporal predicate.

    Satisfied iff P(I~_1 r I~_2) >= γ.
    """
    relation:  AllenRelation
    threshold: float = 0.9   # γ ∈ [0,1]

    def holds(
        self,
        i: FuzzyInterval,
        j: FuzzyInterval,
        tol: float = 1.0,
    ) -> bool:
        """Evaluate TRel~(i, j, relation, threshold)."""
        p = ProbabilisticAllen.confidence(self.relation, i, j, tol)
        return p >= self.threshold

    def confidence(
        self,
        i: FuzzyInterval,
        j: FuzzyInterval,
        tol: float = 1.0,
    ) -> float:
        return ProbabilisticAllen.confidence(self.relation, i, j, tol)


# ── Temporal Validator Π_temp ────────────────────────────────────────────────

@dataclass
class TemporalValidator:
    """
    AION §7.4: Π_temp — validates temporal embedding of fuzzy events.

    Accepts a fuzzy event e~ iff:
        Γ_temp(e~) = P([T^B, T^E] ⊆ stay) >= γ_emb

    Returns the event unchanged if accepted, or None if rejected.
    Used as the gate before AI-generated events enter EventSet.
    """
    gamma_emb: float = 0.9   # γ_emb ∈ [0,1]

    def accept(
        self,
        fuzzy_interval: FuzzyInterval,
        stay:           Interval,
    ) -> bool:
        """True iff Γ_temp(I~) >= γ_emb."""
        p = fuzzy_interval.embedding_probability(stay)
        return p >= self.gamma_emb

    def quality_index(
        self,
        fuzzy_interval: FuzzyInterval,
        stay:           Interval,
    ) -> float:
        """Γ_temp(I~) ∈ [0,1] — continuous quality score."""
        return fuzzy_interval.embedding_probability(stay)


# ── Convenience helpers ───────────────────────────────────────────────────────

def fuzzy_from_interval(interval: Interval) -> FuzzyInterval:
    """Lift an exact Interval into a FuzzyInterval with ε = 0."""
    return FuzzyInterval(
        nominal_start=interval.start,
        nominal_end=interval.end,
        eps_start=0.0,
        eps_end=0.0,
    )


def fuzzy_precedes(i: FuzzyInterval, j: FuzzyInterval, gamma: float = 0.9) -> bool:
    """Convenience: I~ precedes J~ with confidence >= gamma."""
    return ProbabilisticAllen.confidence(AllenRelation.PRECEDES, i, j) >= gamma


def fuzzy_contains(i: FuzzyInterval, j: FuzzyInterval, gamma: float = 0.9) -> bool:
    """Convenience: I~ contains J~ with confidence >= gamma."""
    return ProbabilisticAllen.confidence(AllenRelation.CONTAINS, i, j) >= gamma


def fuzzy_during(i: FuzzyInterval, j: FuzzyInterval, gamma: float = 0.9) -> bool:
    """Convenience: I~ during J~ with confidence >= gamma."""
    return ProbabilisticAllen.confidence(AllenRelation.DURING, i, j) >= gamma
