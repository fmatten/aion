# aion/ai/trajectories.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""
KI-Komponenten Schicht 3: Episoden und Trajektorien nach §21.5.

Implementiert:
  §21.5a  Gelernter Episodenabstand f^(3a): T x R^d -> R>0
  §21.5b  Trajektorienvorhersage   f^(3b): E^m -> Delta(T x R>=0)
  §9.3    Episodenbildungsoperator B_{Phi,Delta}
  §9.4    Klinische Trajektorie J_k = (eps_1, ..., eps_M)
"""
from __future__ import annotations
import math, logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)


# ── §9.3 Episode ──────────────────────────────────────────────────────

@dataclass
class Episode:
    """
    Phi-Episode fuer Patient pk nach §9.3.
    epsilon = (pk, [s,e], Phi, S_epsilon)
    """
    patient_id:   str
    t_begin:      datetime
    t_end:        datetime
    event_types:  list[str]          # Phi
    events:       list = field(default_factory=list, repr=False)
    ep_index:     int  = 0

    @property
    def duration_days(self) -> float:
        return (self.t_end - self.t_begin).total_seconds() / 86400

    def to_dict(self) -> dict:
        return {
            "patient_id":  self.patient_id,
            "ep_index":    self.ep_index,
            "t_begin":     self.t_begin.isoformat(),
            "t_end":       self.t_end.isoformat(),
            "duration_days": round(self.duration_days, 2),
            "event_types": self.event_types,
            "n_events":    len(self.events),
        }


# ── §9.3 Episodenbildungsoperator ─────────────────────────────────────

class EpisodeBuilder:
    """
    Episodenbildungsoperator B_{Phi, Delta} nach §9.3.

    Partitioniert Ereignisse eines Patienten in Cluster mit
    maximalem zeitlichen Abstand delta_gap <= Delta.
    """

    def __init__(self, event_types: list[str], delta_days: float = 30.0):
        self.event_types = set(event_types)
        self.delta_days  = delta_days

    def build(self, events: list, patient_id: str) -> list[Episode]:
        """
        B_{Phi,Delta}(pk) -> Partition in Episoden.
        Jedes Cluster definiert eine Episode.
        """
        # Relevante Ereignisse filtern und sortieren
        relevant = sorted(
            [e for e in events
             if getattr(e, "event_type", "") in self.event_types],
            key=lambda e: getattr(e, "t_start", datetime.min)
        )
        if not relevant:
            return []

        episodes = []
        cluster  = [relevant[0]]

        for ev in relevant[1:]:
            prev_end = getattr(cluster[-1], "t_end",   None) or                        getattr(cluster[-1], "t_start", None)
            curr_start = getattr(ev, "t_start", None)

            if prev_end and curr_start:
                gap = (curr_start - prev_end).total_seconds() / 86400
            else:
                gap = 0.0

            if gap <= self.delta_days:
                cluster.append(ev)
            else:
                episodes.append(self._make_episode(cluster, patient_id, len(episodes)))
                cluster = [ev]

        episodes.append(self._make_episode(cluster, patient_id, len(episodes)))
        log.info("EpisodeBuilder: %d Episoden fuer %s (Delta=%.1fd)",
                 len(episodes), patient_id, self.delta_days)
        return episodes

    def _make_episode(self, cluster: list, patient_id: str, idx: int) -> Episode:
        t_begins = [getattr(e,"t_start",None) for e in cluster if getattr(e,"t_start",None)]
        t_ends   = [getattr(e,"t_end",  None) or getattr(e,"t_start",None)
                    for e in cluster if getattr(e,"t_start",None)]
        t_begin  = min(t_begins) if t_begins else datetime.now(timezone.utc)
        t_end    = max(t_ends)   if t_ends   else t_begin
        return Episode(
            patient_id=patient_id,
            t_begin=t_begin,
            t_end=t_end,
            event_types=list({getattr(e,"event_type","?") for e in cluster}),
            events=cluster,
            ep_index=idx,
        )


# ── §9.4 Klinische Trajektorie ────────────────────────────────────────

@dataclass
class ClinicalTrajectory:
    """
    Klinische Trajektorie J_k = (eps_1, ..., eps_M) nach §9.4.
    Geordnete Folge von Episoden ueber alle Aufenthalte.
    """
    patient_id: str
    episodes:   list[Episode] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.episodes)

    def inter_episode_gaps(self) -> list[float]:
        """Abstande zwischen Episoden in Tagen (delta_gap)."""
        gaps = []
        for i in range(1, len(self.episodes)):
            gap = (self.episodes[i].t_begin -
                   self.episodes[i-1].t_end).total_seconds() / 86400
            gaps.append(max(0.0, gap))
        return gaps

    def type_sequence(self) -> list[str]:
        """Sequenz der dominanten Ereignistypen je Episode."""
        return [ep.event_types[0] if ep.event_types else "?"
                for ep in self.episodes]

    def to_dict(self) -> dict:
        gaps = self.inter_episode_gaps()
        return {
            "patient_id":       self.patient_id,
            "n_episodes":       len(self.episodes),
            "type_sequence":    self.type_sequence(),
            "episodes":         [ep.to_dict() for ep in self.episodes],
            "inter_episode_gaps_days": [round(g,2) for g in gaps],
            "total_duration_days": round(
                (self.episodes[-1].t_end - self.episodes[0].t_begin
                 ).total_seconds() / 86400, 2
            ) if len(self.episodes) >= 2 else 0.0,
        }


# ── §21.5a Gelernter Episodenabstand ─────────────────────────────────

class EpisodeDeltaLearner:
    """
    f^(3a)_theta: T x R^d -> R>0 nach §21.5.

    Schaetzt optimalen Episodenabstand Delta pro Diagnosetyp
    aus beobachteten Trajektorien.
    Verwendet statistisches Modell: Median der beobachteten
    Inter-Episode-Abstaende als Schaetzer.
    """

    def __init__(self):
        self._delta_estimates: dict[str, float] = {}
        self._n_observations:  dict[str, int]   = {}

    def fit(self, trajectories: list[ClinicalTrajectory]) -> None:
        """Lernt Delta aus beobachteten Trajektorien."""
        from collections import defaultdict
        gaps_per_type: dict[str, list[float]] = defaultdict(list)

        for traj in trajectories:
            types = traj.type_sequence()
            gaps  = traj.inter_episode_gaps()
            for i, gap in enumerate(gaps):
                if i < len(types):
                    gaps_per_type[types[i]].append(gap)

        for etype, gaps in gaps_per_type.items():
            sorted_gaps = sorted(gaps)
            n = len(sorted_gaps)
            median = (sorted_gaps[n//2] if n % 2 == 1
                      else (sorted_gaps[n//2-1] + sorted_gaps[n//2]) / 2)
            self._delta_estimates[etype] = max(1.0, median)
            self._n_observations[etype]  = n
            log.info("Delta(%s) = %.1f Tage (n=%d)", etype, median, n)

    def predict_delta(self, event_type: str, default: float = 30.0) -> float:
        """Gibt gelerntes Delta fuer event_type zurueck."""
        return self._delta_estimates.get(event_type, default)

    def summary(self) -> dict:
        return {
            et: {"delta_days": round(d,1),
                 "n_observations": self._n_observations.get(et,0)}
            for et, d in self._delta_estimates.items()
        }


# ── §21.5b Trajektorienvorhersage ─────────────────────────────────────

@dataclass
class TrajectoryPrediction:
    """Vorhersage des naechsten Episodentyps und Zeitabstands."""
    predicted_type:  str
    predicted_gap_days: float
    confidence:      float
    top_k:           list[dict]  # [(type, prob, gap)]

    def to_dict(self) -> dict:
        return {
            "predicted_next_type":     self.predicted_type,
            "predicted_gap_days":      round(self.predicted_gap_days, 1),
            "confidence":              round(self.confidence, 4),
            "top_k_predictions":       self.top_k,
        }


class TrajectoryPredictor:
    """
    f^(3b)_theta: E^m -> Delta(T x R>=0) nach §21.5.

    Bedingte Verteilung ueber naechsten Episodentyp und Zeitabstand:
    P(tau_{m+1}, delta_{m+1} | eps_1, ..., eps_m, theta)

    Implementierung: N-Gramm-Modell ueber Episodentyp-Sequenzen
    (Markov-Annahme 1. Ordnung fuer Typ, Mittelwert fuer Zeitabstand).
    Erweiterbar durch LSTM/Transformer-Modell.
    """

    def __init__(self, order: int = 1):
        self.order = order
        self._transitions: dict[tuple, dict[str, int]] = {}
        self._gaps:        dict[tuple, list[float]]    = {}

    def fit(self, trajectories: list[ClinicalTrajectory]) -> None:
        """Lernt Uebergangswahrscheinlichkeiten aus Trajektorien."""
        from collections import defaultdict
        trans: dict = defaultdict(lambda: defaultdict(int))
        gaps:  dict = defaultdict(list)

        for traj in trajectories:
            types = traj.type_sequence()
            g     = traj.inter_episode_gaps()
            for i in range(self.order, len(types)):
                context = tuple(types[i-self.order:i])
                next_t  = types[i]
                trans[context][next_t] += 1
                if i-1 < len(g):
                    gaps[context + (next_t,)].append(g[i-1])

        self._transitions = {k: dict(v) for k,v in trans.items()}
        self._gaps        = dict(gaps)
        log.info("TrajectoryPredictor: %d Uebergaenge gelernt",
                 sum(sum(v.values()) for v in self._transitions.values()))

    def predict(
        self,
        episode_sequence: list[Episode],
        top_k: int = 3,
    ) -> TrajectoryPrediction | None:
        """
        Vorhersage fuer naechsten Schritt.
        Gibt None zurueck wenn keine Trainingsdaten vorhanden.
        """
        if not episode_sequence:
            return None

        types   = [ep.event_types[0] if ep.event_types else "?"
                   for ep in episode_sequence]
        context = tuple(types[-self.order:])

        if context not in self._transitions:
            # Fallback: letzter Typ wiederholt sich
            pred_type = types[-1] if types else "?"
            return TrajectoryPrediction(
                predicted_type=pred_type,
                predicted_gap_days=30.0,
                confidence=0.3,
                top_k=[{"type":pred_type,"probability":0.3,"gap_days":30.0}],
            )

        counts  = self._transitions[context]
        total   = sum(counts.values())
        probs   = {t: c/total for t,c in counts.items()}
        sorted_p = sorted(probs.items(), key=lambda x: -x[1])

        best_type = sorted_p[0][0]
        best_prob = sorted_p[0][1]

        # Erwarteter Zeitabstand
        gap_key = context + (best_type,)
        gap_vals = self._gaps.get(gap_key, [30.0])
        mean_gap = sum(gap_vals) / len(gap_vals)

        top_k_list = []
        for t, p in sorted_p[:top_k]:
            gk = context + (t,)
            gv = self._gaps.get(gk, [30.0])
            top_k_list.append({
                "type":        t,
                "probability": round(p, 4),
                "gap_days":    round(sum(gv)/len(gv), 1),
            })

        return TrajectoryPrediction(
            predicted_type=best_type,
            predicted_gap_days=mean_gap,
            confidence=best_prob,
            top_k=top_k_list,
        )

    def has_training_data(self) -> bool:
        return len(self._transitions) > 0

    def to_dict(self) -> dict:
        """Serialisiert Modell fuer Persistenz."""
        return {
            "order": self.order,
            "transitions": {
                "|".join(k): v for k, v in self._transitions.items()
            },
            "gaps": {
                "|".join(k): v for k, v in self._gaps.items()
            },
        }

    def load_dict(self, data: dict) -> None:
        """Laedt Modell aus serialisiertem Zustand."""
        self.order = data.get("order", 1)
        self._transitions = {
            tuple(k.split("|")): v
            for k, v in data.get("transitions", {}).items()
        }
        self._gaps = {
            tuple(k.split("|")): v
            for k, v in data.get("gaps", {}).items()
        }
        log.info("TrajectoryPredictor geladen: %d Kontexte, %d Uebergaenge",
                 len(self._transitions),
                 sum(sum(v.values()) for v in self._transitions.values()))


# ── Validierungsoperator fuer Trajektorien ────────────────────────────

class TrajectoryValidator:
    """
    Validierungsoperator Pi_3 fuer Trajektorien nach §21.2.
    Prueft:
      - Zeitliche Ordnung: t_end(eps_j) < t_begin(eps_{j+1})
      - Minimale Episodenanzahl
      - Konfidenz >= c_min
    """

    def __init__(self, min_episodes: int = 1, c_min: float = 0.0):
        self.min_episodes = min_episodes
        self.c_min        = c_min

    def validate(
        self, traj: ClinicalTrajectory, confidence: float = 1.0
    ) -> dict:
        violations = []

        if len(traj.episodes) < self.min_episodes:
            violations.append(
                f"Zu wenige Episoden: {len(traj.episodes)} < {self.min_episodes}"
            )

        if confidence < self.c_min:
            violations.append(
                f"Konfidenz {confidence:.3f} < c_min {self.c_min:.3f}"
            )

        # Zeitliche Ordnung pruefen
        for i in range(1, len(traj.episodes)):
            if traj.episodes[i].t_begin < traj.episodes[i-1].t_end:
                violations.append(
                    f"Zeitliche Ordnung verletzt: Episode {i} "
                    f"beginnt vor Ende Episode {i-1}"
                )

        return {
            "accepted":   len(violations) == 0,
            "violations": violations,
            "n_episodes": len(traj.episodes),
            "confidence": round(confidence, 4),
        }
