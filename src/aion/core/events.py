# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""ClinicalEvent — Ereignismodell e = (p, a, τ, α, ρ) gemäß AION_v1.0 (erweitert).

Mathematisches Modell:
    e = (p, a, τ, α, ρ) mit:
        p ∈ P:   Patient
        a ∈ A:   Aufenthalt mit Zeitintervall [t_B, t_E] ⊆ a
        τ ∈ T:   Ereignistyp (aus TypeHierarchy)
        α:       Attributbelegung α(a_j) ∈ V_j
        ρ : E → R   Funktion zu typisierten Beziehungen (R = Vokabular der Relations)

Erweiterung gegenüber AION_v1.0: Statt einer ungetypten Menge ρ ⊆ E
verwendet diese Implementierung typisierte Beziehungen (siehe core.relations).
Das macht den Knowledge-Graph explizit — eine Beobachtung ist nicht
einfach „mit der Diagnose verbunden", sondern entweder `confirms`,
`rules_out` oder `observation_of`.

Backwards-Compat: Wer ein altes Set übergibt, bekommt automatisch alle
Beziehungen als EventRelation.REFERENCES eingetragen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union
import json
import uuid

from aion.core.relations import EventRelation, is_valid_relation


@dataclass
class ClinicalEvent:
    """Klinisches Ereignis mit typisierten Referenzen."""

    patient_id: str
    event_type: str
    t_start: datetime
    t_end: datetime
    stay_start: datetime
    stay_end: datetime
    attributes: dict[str, Any] = field(default_factory=dict)
    # ρ : referenzierte_event_id → relation_string
    references: dict[str, str] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    confidence: float = 1.0  # γ-Konfidenzmaß für unscharfe Ereignisse

    def __post_init__(self) -> None:
        # Backwards-Compat: Set/Liste/Tuple → Dict mit Default-Relation
        if isinstance(self.references, (set, list, tuple)):
            self.references = {ref: EventRelation.REFERENCES for ref in self.references}
        # Validierung der Relation-Strings
        if self.references:
            for ref_id, rel in self.references.items():
                if not is_valid_relation(rel):
                    raise ValueError(
                        f"Ungültiger Relation-Bezeichner: {rel!r} "
                        f"(nur lowercase ASCII + Underscore erlaubt)"
                    )

    # ────────────────────────────────────────────────────────────────
    # Referenz-API
    # ────────────────────────────────────────────────────────────────
    def add_reference(
        self,
        target: Union[str, "ClinicalEvent"],
        relation: str = EventRelation.REFERENCES,
    ) -> None:
        """Fügt eine typisierte Referenz hinzu."""
        ref_id = target.event_id if isinstance(target, ClinicalEvent) else target
        if not is_valid_relation(relation):
            raise ValueError(f"Ungültiger Relation-Bezeichner: {relation!r}")
        self.references[ref_id] = relation

    def remove_reference(self, target: Union[str, "ClinicalEvent"]) -> bool:
        ref_id = target.event_id if isinstance(target, ClinicalEvent) else target
        return self.references.pop(ref_id, None) is not None

    def references_with_relation(self, relation: str) -> set[str]:
        """Alle referenzierten Event-IDs mit der angegebenen Beziehung."""
        return {rid for rid, r in self.references.items() if r == relation}

    def relation_to(self, target: Union[str, "ClinicalEvent"]) -> Optional[str]:
        ref_id = target.event_id if isinstance(target, ClinicalEvent) else target
        return self.references.get(ref_id)

    # ────────────────────────────────────────────────────────────────
    # Validierung
    # ────────────────────────────────────────────────────────────────
    def is_temporally_embedded(self) -> bool:
        """Prüft [t_B(e), t_E(e)] ⊆ a(e)."""
        return (
            self.stay_start <= self.t_start
            and self.t_end <= self.stay_end
            and self.t_start <= self.t_end
        )

    def duration_seconds(self) -> float:
        return (self.t_end - self.t_start).total_seconds()

    def overlaps_with(self, other: "ClinicalEvent") -> bool:
        """Allen-Überlappung (loose)."""
        return self.t_start < other.t_end and other.t_start < self.t_end

    # ────────────────────────────────────────────────────────────────
    # Serialisierung
    # ────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "patient_id": self.patient_id,
            "event_type": self.event_type,
            "t_start": self.t_start.isoformat(),
            "t_end": self.t_end.isoformat(),
            "stay_start": self.stay_start.isoformat(),
            "stay_end": self.stay_end.isoformat(),
            "attributes": dict(self.attributes),
            "references": dict(self.references),
            "confidence": self.confidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "ClinicalEvent":
        refs = d.get("references", {}) or {}
        # Akzeptiert sowohl alte (Liste) als auch neue (Dict) Form
        if isinstance(refs, (list, set, tuple)):
            refs = {r: EventRelation.REFERENCES for r in refs}
        return cls(
            patient_id=d["patient_id"],
            event_type=d["event_type"],
            t_start=cls._parse_dt(d["t_start"]),
            t_end=cls._parse_dt(d["t_end"]),
            stay_start=cls._parse_dt(d["stay_start"]),
            stay_end=cls._parse_dt(d["stay_end"]),
            attributes=d.get("attributes", {}) or {},
            references=refs,
            event_id=d.get("event_id", str(uuid.uuid4())),
            confidence=d.get("confidence", 1.0),
        )

    @staticmethod
    def _parse_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def __hash__(self) -> int:
        return hash(self.event_id)
