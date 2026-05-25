# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Temporale Algebra — alle 13 Allen-Relationen + unscharfe Intervalle.

Mathematisches Modell:
    Für I1 = [a, b], I2 = [c, d] mit a ≤ b, c ≤ d gibt es
    genau 13 disjunkte und erschöpfende Relationen:

        before        b < c
        meets         b = c
        overlaps      a < c < b < d
        starts        a = c ∧ b < d
        during        a > c ∧ b < d
        finishes      b = d ∧ a > c
        equals        a = c ∧ b = d
        finished_by   b = d ∧ a < c
        contains      a < c ∧ b > d
        started_by    a = c ∧ b > d
        overlapped_by c < a < d < b
        met_by        a = d
        after         a > d
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AllenInterval:
    """Geschlossenes Zeitintervall [start, end] mit start ≤ end."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Intervall mit end < start: [{self.start}, {self.end}]")

    # ── Die 13 Allen-Relationen ──────────────────────────────────
    def before(self, o: "AllenInterval") -> bool:        return self.end < o.start
    def meets(self, o: "AllenInterval") -> bool:         return self.end == o.start
    def overlaps(self, o: "AllenInterval") -> bool:      return self.start < o.start < self.end < o.end
    def starts(self, o: "AllenInterval") -> bool:        return self.start == o.start and self.end < o.end
    def during(self, o: "AllenInterval") -> bool:        return self.start > o.start and self.end < o.end
    def finishes(self, o: "AllenInterval") -> bool:      return self.end == o.end and self.start > o.start
    def equals(self, o: "AllenInterval") -> bool:        return self.start == o.start and self.end == o.end
    def finished_by(self, o: "AllenInterval") -> bool:   return self.end == o.end and self.start < o.start
    def contains(self, o: "AllenInterval") -> bool:      return self.start < o.start and self.end > o.end
    def started_by(self, o: "AllenInterval") -> bool:    return self.start == o.start and self.end > o.end
    def overlapped_by(self, o: "AllenInterval") -> bool: return o.start < self.start < o.end < self.end
    def met_by(self, o: "AllenInterval") -> bool:        return self.start == o.end
    def after(self, o: "AllenInterval") -> bool:         return self.start > o.end

    def relation_to(self, o: "AllenInterval") -> str:
        """Liefert genau eine der 13 Allen-Relationen als Bezeichner."""
        for r in ALL_RELATIONS:
            if getattr(self, r)(o):
                return r
        return "?"  # unmöglich, wenn Definition vollständig

    # ── Hilfsmethoden ────────────────────────────────────────────
    def length(self) -> float:
        return self.end - self.start

    def __repr__(self) -> str:
        return f"[{self.start},{self.end}]"


ALL_RELATIONS = (
    "before", "meets", "overlaps", "starts", "during", "finishes",
    "equals", "finished_by", "contains", "started_by", "overlapped_by",
    "met_by", "after",
)

ALLEN_RELATIONS = {r: getattr(AllenInterval, r) for r in ALL_RELATIONS}


@dataclass(frozen=True)
class FuzzyAllenInterval:
    """Unscharfes Intervall mit Unsicherheit: [start ± ε_s, end ± ε_e].

    Verwendet normalverteilte Zeitpunkte, P(I1 r I2) wird via Monte-Carlo
    geschätzt. Ohne numpy-Abhängigkeit (random aus stdlib).
    """

    start: float
    end: float
    epsilon_start: float = 0.0
    epsilon_end: float = 0.0

    def sample(self, rng=None) -> AllenInterval:
        """Zieht eine konkrete Realisierung."""
        import random as _random
        rng = rng or _random
        s = rng.gauss(self.start, self.epsilon_start) if self.epsilon_start > 0 else self.start
        e = rng.gauss(self.end, self.epsilon_end) if self.epsilon_end > 0 else self.end
        if e < s:
            s, e = e, s
        return AllenInterval(s, e)

    def confidence(
        self,
        other: "FuzzyAllenInterval",
        relation: str,
        n_samples: int = 1000,
        seed: Optional[int] = None,
    ) -> float:
        """Schätzt P(self r other) via Monte-Carlo."""
        import random as _random
        rng = _random.Random(seed)
        if relation not in ALL_RELATIONS:
            raise ValueError(f"Unbekannte Relation: {relation}")
        rel_fn = ALLEN_RELATIONS[relation]
        hits = 0
        for _ in range(n_samples):
            i1 = self.sample(rng)
            i2 = other.sample(rng)
            if rel_fn(i1, i2):
                hits += 1
        return hits / n_samples

    def confidence_distribution(
        self,
        other: "FuzzyAllenInterval",
        n_samples: int = 1000,
        seed: Optional[int] = None,
    ) -> dict[str, float]:
        """Schätzt P(self r other) für ALLE 13 Relationen in einem Pass."""
        import random as _random
        rng = _random.Random(seed)
        counts = {r: 0 for r in ALL_RELATIONS}
        for _ in range(n_samples):
            i1 = self.sample(rng)
            i2 = other.sample(rng)
            counts[i1.relation_to(i2)] += 1
        return {r: c / n_samples for r, c in counts.items()}
