# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.abstraction.trajectory
===========================
AION §9.4: Clinical Trajectories (Level 4 Abstraction).

A clinical trajectory of patient p_k is an ordered sequence
    J_k = (ε_1, ε_2, ..., ε_M)
of episodes with t^E(ε_j) < t^B(ε_{j+1}).

Key operations:
  - Pattern matching: π is a subpattern of J_k
  - Gap analysis: temporal distances between consecutive episodes
  - Subsequence extraction: all sub-trajectories matching criteria
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..core.allen import AllenRelation, classify, Interval
from .episode import Episode, EpisodeIndex


# ── Trajectory ────────────────────────────────────────────────────────────────

@dataclass
class Trajectory:
    """
    AION §9.4: Clinical trajectory J_k = (ε_1, ..., ε_M).

    patient_id : str
    episodes   : list[Episode], sorted by t^B (enforced on creation)

    Invariant: t^E(ε_j) < t^B(ε_{j+1}) for all j  (AION §9.4)
    """
    patient_id: str
    episodes:   list[Episode] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Sort and validate ordering invariant
        self.episodes = sorted(self.episodes, key=lambda e: e.interval.start)
        self._validate_ordering()

    def _validate_ordering(self) -> None:
        for i in range(len(self.episodes) - 1):
            a = self.episodes[i]
            b = self.episodes[i + 1]
            if a.interval.end >= b.interval.start:
                raise ValueError(
                    f"AION §9.4 violation: episode {i} ends at "
                    f"{a.interval.end} but episode {i+1} starts at "
                    f"{b.interval.start} — not strictly ordered"
                )

    # ── Basic properties ──────────────────────────────────────────────────────

    @property
    def length(self) -> int:
        return len(self.episodes)

    @property
    def is_empty(self) -> bool:
        return self.length == 0

    @property
    def total_span(self) -> Optional[Interval]:
        if self.is_empty:
            return None
        return Interval(
            self.episodes[0].interval.start,
            self.episodes[-1].interval.end,
        )

    def gap_between(self, i: int, j: int) -> datetime.timedelta:
        """Gap between episode i and episode j (i < j)."""
        return self.episodes[i].gap_to(self.episodes[j])

    def consecutive_gaps(self) -> list[datetime.timedelta]:
        """List of gaps between consecutive episodes."""
        return [
            self.episodes[i].gap_to(self.episodes[i + 1])
            for i in range(self.length - 1)
        ]

    # ── Pattern matching ──────────────────────────────────────────────────────

    def has_pattern(self, pattern: "TrajectoryPattern") -> bool:
        """
        AION §9.4: Pattern(J_k, π) — π is a (possibly non-contiguous)
        subpattern of J_k.
        """
        return pattern.matches(self)

    def find_pattern(
        self, pattern: "TrajectoryPattern"
    ) -> list[list[Episode]]:
        """Return all matches of *pattern* in this trajectory."""
        return pattern.find_all(self)

    # ── Subsequences ─────────────────────────────────────────────────────────

    def subsequence(self, start: int, end: int) -> "Trajectory":
        """Return sub-trajectory from index *start* to *end* (inclusive)."""
        eps = self.episodes[start : end + 1]
        # Build with validation disabled (already sorted by parent)
        t = Trajectory.__new__(Trajectory)
        t.patient_id = self.patient_id
        t.episodes = list(eps)
        return t

    def episodes_of_type(self, *type_names: str) -> list[Episode]:
        """All episodes whose type_set intersects with type_names."""
        result = []
        for ep in self.episodes:
            if ep.type_set.intersection(type_names):
                result.append(ep)
        return result

    def __getitem__(self, idx: int) -> Episode:
        return self.episodes[idx]

    def __iter__(self):
        return iter(self.episodes)

    def __repr__(self) -> str:
        span = self.total_span
        return (
            f"Trajectory(p={self.patient_id!r}, "
            f"M={self.length}, "
            f"span={span!r})"
        )


# ── TrajectoryPattern ─────────────────────────────────────────────────────────

@dataclass
class EpisodePredicate:
    """
    A predicate that an episode must satisfy to match one pattern slot.

    type_set     : frozenset[str] — episode type_set must intersect
    min_count    : int — minimum number of constituent events
    max_gap_from_prev : float | None — max gap (seconds) from preceding match
    min_gap_from_prev : float | None — min gap (seconds) from preceding match
    custom       : callable Episode → bool — additional custom check
    """
    type_set:            frozenset[str]
    min_count:           int = 0   # 0 = no minimum (episodes with empty event list valid)
    max_gap_from_prev:   Optional[float] = None  # seconds
    min_gap_from_prev:   Optional[float] = None  # seconds
    custom:              Optional[Callable[[Episode], bool]] = None

    def matches_episode(self, ep: Episode) -> bool:
        if not ep.type_set.intersection(self.type_set):
            return False
        if ep.event_count < self.min_count:
            return False
        if self.custom and not self.custom(ep):
            return False
        return True

    def gap_ok(
        self, gap: datetime.timedelta
    ) -> bool:
        gap_s = gap.total_seconds()
        if self.max_gap_from_prev is not None and gap_s > self.max_gap_from_prev:
            return False
        if self.min_gap_from_prev is not None and gap_s < self.min_gap_from_prev:
            return False
        return True


class TrajectoryPattern:
    """
    AION §9.4: Pattern π = (pred_1, pred_2, ..., pred_n).

    Matches a sub-sequence (possibly non-contiguous) of a trajectory where:
      - episode i_j matches pred_j
      - gap between consecutive matches satisfies gap constraints in pred_{j+1}
    """

    def __init__(self, predicates: list[EpisodePredicate]) -> None:
        if not predicates:
            raise ValueError("TrajectoryPattern requires at least one predicate")
        self.predicates = predicates

    def matches(self, trajectory: Trajectory) -> bool:
        """True iff at least one matching subsequence exists."""
        return len(self.find_all(trajectory)) > 0

    def find_all(
        self, trajectory: Trajectory
    ) -> list[list[Episode]]:
        """
        Return all non-overlapping matches of the pattern in *trajectory*.
        Uses recursive backtracking over episode indices.
        """
        results: list[list[Episode]] = []
        self._search(
            trajectory.episodes,
            pred_idx=0,
            ep_idx=0,
            current=[],
            results=results,
        )
        return results

    def _search(
        self,
        episodes: list[Episode],
        pred_idx: int,
        ep_idx:   int,
        current:  list[Episode],
        results:  list[list[Episode]],
    ) -> None:
        if pred_idx == len(self.predicates):
            results.append(list(current))
            return

        pred = self.predicates[pred_idx]

        for i in range(ep_idx, len(episodes)):
            ep = episodes[i]
            if not pred.matches_episode(ep):
                continue

            # Gap check against last matched episode
            if current:
                gap = current[-1].gap_to(ep)
                if not pred.gap_ok(gap):
                    continue

            current.append(ep)
            self._search(episodes, pred_idx + 1, i + 1, current, results)
            current.pop()

    def __repr__(self) -> str:
        return f"TrajectoryPattern({len(self.predicates)} predicates)"


# ── TrajectoryBuilder ─────────────────────────────────────────────────────────

class TrajectoryBuilder:
    """
    Construct Trajectory objects for all patients from an EpisodeIndex.

    Merges episodes across multiple type_sets, sorts them, and produces
    one Trajectory per patient.
    """

    def __init__(self, episode_index: EpisodeIndex) -> None:
        self._index = episode_index

    def build(self, patient_id: str) -> Optional[Trajectory]:
        """Build the complete trajectory for a single patient."""
        episodes = self._index.all_for_patient(patient_id)
        if not episodes:
            return None

        # Check for overlapping episodes (warn but still build)
        episodes.sort(key=lambda e: e.interval.start)
        filtered = self._remove_overlapping(episodes)

        t = Trajectory.__new__(Trajectory)
        t.patient_id = patient_id
        t.episodes   = filtered
        return t

    def build_all(
        self, patient_ids: Optional[list[str]] = None
    ) -> dict[str, Trajectory]:
        """Build trajectories for all (or specified) patients."""
        pids = patient_ids or list({
            ep.patient_id
            for eps in self._index._store.values()
            for ep in eps
        })
        result: dict[str, Trajectory] = {}
        for pid in pids:
            t = self.build(pid)
            if t is not None:
                result[pid] = t
        return result

    @staticmethod
    def _remove_overlapping(episodes: list[Episode]) -> list[Episode]:
        """
        Remove episodes that overlap with the previous one.
        Keeps the longer episode when conflict arises.
        AION §9.4: t^E(ε_j) < t^B(ε_{j+1}) must hold.
        """
        if not episodes:
            return []
        kept = [episodes[0]]
        for ep in episodes[1:]:
            last = kept[-1]
            if ep.interval.start > last.interval.end:
                kept.append(ep)
            else:
                # Keep whichever is longer
                if ep.duration > last.duration:
                    kept[-1] = ep
        return kept
