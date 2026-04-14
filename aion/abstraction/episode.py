# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.abstraction.episode
========================
AION §9.3: Clinical Episodes (Level 3 Abstraction).

A Φ-episode for patient p_k is a tuple
    ε = (p_k, [s, e], Φ, S_ε)
where:
    Φ   : set of event types forming the episode
    [s,e]: episode interval = [min t^B, max t^E] over S_ε
    S_ε : constituent events — all events of p_k with type ∈ Φ in [s,e]

The EpisodeFormationOperator B_{Φ,Δ} clusters events by gap ≤ Δ seconds.

AION §9.2 Derived Events are also implemented here:
    DerivedEvent = ρ(S) with [min t^B(S), max t^E(S)] as interval.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional

from ..core.allen import Interval, AllenRelation, classify
from ..core.event import ClinicalEvent, EventSet
from ..core.types import TypeHierarchy, default_hierarchy


# ── Episode ───────────────────────────────────────────────────────────────────

@dataclass
class Episode:
    """
    AION §9.3: Φ-episode ε = (patient_id, [s,e], type_set, events, index).

    patient_id   : str
    interval     : Interval [s, e] = convex hull of constituent events
    type_set     : frozenset[str] — Φ, the defining event types
    events       : list[ClinicalEvent] — S_ε, sorted by t^B
    index        : int — episode ordinal for this patient/type_set (1-based)
    """
    patient_id:  str
    interval:    Interval
    type_set:    frozenset[str]
    events:      list[ClinicalEvent]
    index:       int = 1

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def t_begin(self) -> datetime.datetime:
        return self.interval.start

    @property
    def t_end(self) -> datetime.datetime:
        return self.interval.end

    @property
    def duration(self) -> datetime.timedelta:
        return self.interval.duration

    @property
    def event_count(self) -> int:
        return len(self.events)

    def gap_to(self, other: "Episode") -> datetime.timedelta:
        """
        AION §9.3: δ_gap(ε_1, ε_2) = max(0, t^B(ε_2) - t^E(ε_1)).
        Assumes self precedes other.
        """
        gap = (other.interval.start - self.interval.end).total_seconds()
        return datetime.timedelta(seconds=max(0.0, gap))

    def allen_relation(self, other: "Episode") -> AllenRelation:
        return classify(self.interval, other.interval)

    def contains_event(self, event_id: str) -> bool:
        return any(e.id == event_id for e in self.events)

    def __repr__(self) -> str:
        return (
            f"Episode(p={self.patient_id!r}, idx={self.index}, "
            f"Φ={set(self.type_set)}, "
            f"τ=[{self.t_begin:%H:%M}–{self.t_end:%H:%M}], "
            f"n={self.event_count})"
        )

    def __lt__(self, other: "Episode") -> bool:
        return self.interval.start < other.interval.start


# ── DerivedEvent ──────────────────────────────────────────────────────────────

@dataclass
class DerivedEvent:
    """
    AION §9.2: Derived event e_der = ρ(S).

    Generated from a source event set S ⊂ E by a derivation rule ρ.
    The interval is the convex hull: [min t^B(S), max t^E(S)].
    """
    derived_type:  str
    patient_id:    str
    stay_id:       str
    source_events: list[ClinicalEvent]
    rule_name:     str = "custom"
    metadata:      dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_events:
            raise ValueError("DerivedEvent requires at least one source event")
        starts = [e.tau.start for e in self.source_events]
        ends   = [e.tau.end   for e in self.source_events]
        self._interval = Interval(min(starts), max(ends))

    @property
    def interval(self) -> Interval:
        return self._interval

    @property
    def event_count(self) -> int:
        return len(self.source_events)

    def to_clinical_event(self) -> ClinicalEvent:
        """Materialise as a ClinicalEvent for insertion into EventSet."""
        return ClinicalEvent(
            patient_id=self.patient_id,
            stay_id=self.stay_id,
            type=self.derived_type,
            tau=self._interval,
            attributes={
                "rule":       self.rule_name,
                "source_ids": [e.id for e in self.source_events],
                **self.metadata,
            },
        )

    def __repr__(self) -> str:
        return (
            f"DerivedEvent(type={self.derived_type!r}, "
            f"rule={self.rule_name!r}, n={self.event_count})"
        )


# ── EpisodeFormationOperator ──────────────────────────────────────────────────

class EpisodeFormationOperator:
    """
    AION §9.3: B_{Φ,Δ} — cluster events of types Φ by gap ≤ Δ seconds.

    Algorithm:
      1. Collect events of patient p_k with type ∈ Φ (subtypes included).
      2. Sort by t^B.
      3. Greedily cluster: merge into current cluster if gap to previous
         event ≤ Δ; otherwise start new cluster.
      4. Each cluster → one Episode with index 1, 2, ...

    For Φ = {τ_dx} and single diagnosis code, this reduces to FM-1
    episode formation.
    """

    def __init__(
        self,
        type_set: frozenset[str],
        delta:    float,              # max gap in seconds
        hierarchy: Optional[TypeHierarchy] = None,
    ) -> None:
        self.type_set  = type_set
        self.delta     = delta
        self._h        = hierarchy or default_hierarchy()

    # ── Core operator ─────────────────────────────────────────────────────────

    def __call__(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> list[Episode]:
        """B_{Φ,Δ}(p_k) — produce episodes for patient p_k."""
        return self.form(patient_id, event_set)

    def form(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> list[Episode]:
        """
        Form all Φ-episodes for patient *patient_id*.
        Returns episodes sorted by start time, indexed from 1.
        """
        # Collect qualifying events (type ∈ Φ or subtype of Φ-member)
        candidates: list[ClinicalEvent] = []
        for t in self.type_set:
            candidates.extend(event_set.by_type(t))

        # Keep only events of this patient
        candidates = [
            e for e in candidates if e.patient_id == patient_id
        ]

        if not candidates:
            return []

        # Sort by start time
        candidates.sort(key=lambda e: e.tau.start)

        # Greedy clustering
        clusters: list[list[ClinicalEvent]] = []
        current: list[ClinicalEvent] = [candidates[0]]

        for evt in candidates[1:]:
            last = current[-1]
            gap = (evt.tau.start - last.tau.end).total_seconds()
            if gap <= self.delta:
                current.append(evt)
            else:
                clusters.append(current)
                current = [evt]
        clusters.append(current)

        # Build Episode objects
        episodes: list[Episode] = []
        for idx, cluster in enumerate(clusters, start=1):
            starts = [e.tau.start for e in cluster]
            ends   = [e.tau.end   for e in cluster]
            eps_interval = Interval(min(starts), max(ends))
            episodes.append(Episode(
                patient_id=patient_id,
                interval=eps_interval,
                type_set=self.type_set,
                events=cluster,
                index=idx,
            ))

        return episodes

    def form_all(self, event_set: EventSet) -> dict[str, list[Episode]]:
        """Form episodes for ALL patients in event_set."""
        return {
            pid: self.form(pid, event_set)
            for pid in event_set.all_patients
        }


# ── EpisodeIndex ──────────────────────────────────────────────────────────────

class EpisodeIndex:
    """
    Cache of episodes per (patient_id, type_set) produced by formation operators.
    Supports the Episode() predicate in the query language (AION §10.1).
    """

    def __init__(self) -> None:
        # key: (patient_id, type_set_key) → sorted episodes
        self._store: dict[tuple[str, str], list[Episode]] = {}

    @staticmethod
    def _key(patient_id: str, type_set: frozenset[str]) -> tuple[str, str]:
        return (patient_id, ",".join(sorted(type_set)))

    def add(self, episode: Episode) -> None:
        k = self._key(episode.patient_id, episode.type_set)
        self._store.setdefault(k, []).append(episode)
        self._store[k].sort()

    def add_many(self, episodes: list[Episode]) -> None:
        for ep in episodes:
            self.add(ep)

    def get(
        self,
        patient_id: str,
        type_set:   frozenset[str],
        index:      Optional[int] = None,
    ) -> list[Episode]:
        """
        Return episodes for patient + type_set.
        If index is given, return the single episode at that 1-based ordinal.
        """
        k   = self._key(patient_id, type_set)
        eps = self._store.get(k, [])
        if index is not None:
            return [e for e in eps if e.index == index]
        return eps

    def count(self, patient_id: str, type_set: frozenset[str]) -> int:
        return len(self.get(patient_id, type_set))

    def all_for_patient(self, patient_id: str) -> list[Episode]:
        return [
            ep
            for (pid, _), eps in self._store.items()
            if pid == patient_id
            for ep in eps
        ]

    def populate_from_operator(
        self,
        operator:  EpisodeFormationOperator,
        event_set: EventSet,
    ) -> None:
        """Run *operator* for all patients and store results."""
        for pid, episodes in operator.form_all(event_set).items():
            self.add_many(episodes)

    def __len__(self) -> int:
        return sum(len(v) for v in self._store.values())

    def __repr__(self) -> str:
        return f"EpisodeIndex({len(self)} episodes)"
