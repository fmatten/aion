# aion/privacy/dp.py - Differential Privacy §20 AION-Paper
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
from __future__ import annotations
import math, random, logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class PrivacyBudgetExhausted(Exception):
    pass


class PrivacyBudget:
    def __init__(self, epsilon_total: float):
        if epsilon_total <= 0:
            raise ValueError(f"epsilon_ges muss > 0 sein")
        self._total     = epsilon_total
        self._remaining = epsilon_total
        self._consumed  = 0.0
        self._queries   = 0

    @property
    def remaining(self): return self._remaining
    @property
    def consumed(self): return self._consumed
    @property
    def total(self): return self._total

    def consume(self, epsilon: float) -> None:
        if epsilon <= 0: raise ValueError("epsilon muss > 0 sein")
        if epsilon > self._remaining + 1e-10:
            raise PrivacyBudgetExhausted(
                f"Budget erschoepft: angefordert={epsilon:.4f}, "
                f"verbleibend={self._remaining:.4f}"
            )
        self._remaining -= epsilon
        self._consumed  += epsilon
        self._queries   += 1
        log.info("DP consumed=%.4f remaining=%.4f (#%d)",
                 epsilon, self._remaining, self._queries)

    def epsilon_per_query(self, n: int) -> float:
        return self._remaining / n

    def status(self) -> dict:
        return {
            "epsilon_total":     self._total,
            "epsilon_consumed":  round(self._consumed,  6),
            "epsilon_remaining": round(self._remaining, 6),
            "queries_executed":  self._queries,
            "budget_exhausted":  self._remaining < 1e-10,
        }


class LaplaceDP:
    def __init__(self, epsilon: float, sensitivity: float = 1.0):
        if epsilon <= 0: raise ValueError("epsilon muss > 0")
        if sensitivity <= 0: raise ValueError("sensitivity muss > 0")
        self.epsilon     = epsilon
        self.sensitivity = sensitivity
        self._scale      = sensitivity / epsilon

    def _sample(self) -> float:
        u = random.uniform(-0.5, 0.5)
        return -self._scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))

    def release(self, v: float) -> float:
        return v + self._sample()

    def release_count(self, n: int) -> float:
        return self.release(float(n))

    @property
    def expected_error(self) -> float:
        return self._scale

    def privacy_guarantee(self) -> dict:
        return {
            "mechanism": "Laplace",
            "epsilon": self.epsilon,
            "sensitivity": self.sensitivity,
            "scale": round(self._scale, 6),
            "expected_absolute_error": round(self.expected_error, 6),
            "privacy_level": (
                "stark" if self.epsilon <= 1.0 else
                "moderat" if self.epsilon <= 5.0 else "schwach"
            ),
        }


class LocalDP:
    def __init__(self, epsilon: float):
        self._dp = LaplaceDP(epsilon=epsilon, sensitivity=1.0)
        self.epsilon = epsilon

    def release_local_count(self, n: int) -> float:
        return self._dp.release_count(n)

    @staticmethod
    def aggregate(results: list) -> float:
        return sum(results)

    @staticmethod
    def federated_variance(epsilons: list) -> float:
        return sum(2.0 / (e ** 2) for e in epsilons)

    @staticmethod
    def federated_std_error(epsilons: list) -> float:
        return math.sqrt(LocalDP.federated_variance(epsilons))


class QuerySensitivity:
    @staticmethod
    def cohort_size() -> float: return 1.0
    @staticmethod
    def pattern_frequency() -> float: return 1.0
    @staticmethod
    def mean_observation(n: int, vmin: float, vmax: float) -> float:
        if n <= 0: raise ValueError("n muss > 0 sein")
        return (vmax - vmin) / n
    @staticmethod
    def event_count() -> float: return 1.0


@dataclass
class DPQueryResult:
    noisy_value:   float
    epsilon_used:  float
    sensitivity:   float
    mechanism:     str   = "Laplace"
    privacy_level: str   = "moderat"
    true_value:    float = None

    def to_dict(self) -> dict:
        return {
            "value":          round(self.noisy_value, 4),
            "epsilon_used":   round(self.epsilon_used, 6),
            "mechanism":      self.mechanism,
            "privacy_level":  self.privacy_level,
            "expected_error": round(self.sensitivity / self.epsilon_used, 4),
        }


class DPQueryEngine:
    def __init__(self, budget: PrivacyBudget, mechanism: str = "Laplace"):
        self._budget = budget
        self._mechanism = mechanism

    def cohort_count(self, true_count: int, epsilon: float = None) -> DPQueryResult:
        eps = epsilon or self._budget.remaining
        self._budget.consume(eps)
        dp = LaplaceDP(epsilon=eps, sensitivity=1.0)
        return DPQueryResult(
            noisy_value=max(0.0, dp.release_count(true_count)),
            epsilon_used=eps, sensitivity=1.0,
            privacy_level=dp.privacy_guarantee()["privacy_level"],
        )

    def mean_value(self, true_mean: float, cohort_size: int,
                   value_min: float, value_max: float,
                   epsilon: float = None) -> DPQueryResult:
        eps  = epsilon or self._budget.remaining
        sens = QuerySensitivity.mean_observation(cohort_size, value_min, value_max)
        self._budget.consume(eps)
        dp = LaplaceDP(epsilon=eps, sensitivity=sens)
        return DPQueryResult(
            noisy_value=dp.release(true_mean),
            epsilon_used=eps, sensitivity=sens,
            privacy_level=dp.privacy_guarantee()["privacy_level"],
        )

    def pattern_frequency(self, true_freq: int, epsilon: float = None) -> DPQueryResult:
        eps = epsilon or self._budget.remaining
        self._budget.consume(eps)
        dp = LaplaceDP(epsilon=eps, sensitivity=1.0)
        return DPQueryResult(
            noisy_value=max(0.0, dp.release_count(true_freq)),
            epsilon_used=eps, sensitivity=1.0,
            privacy_level=dp.privacy_guarantee()["privacy_level"],
        )

    @property
    def budget_status(self) -> dict:
        return self._budget.status()
