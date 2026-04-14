# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.core.event
===============
AION §4–§5: Universal Event Model.

e = (p, a, τ, [t^B, t^E], α, ρ)
    p   : patient identifier
    a   : stay identifier
    τ   : type ∈ T (node in TypeHierarchy)
    [t^B, t^E] : Interval (temporal embedding)
    α   : attribute dict conforming to σ(τ)
    ρ   : set of reference event IDs (parent processes)

Consistency conditions (AION §5.2):
  1. Temporal embedding  : [t^B, t^E] ⊆ stay interval
  2. Type schema         : α satisfies σ(τ) required attributes
  3. Referential integrity: ρ ⊆ E, all references same patient
  4. Uniqueness          : α["id"] globally unique

Extensions over SILD ClinicalEvent:
  - ρ (reference set) replaces bare dict
  - confidence c ∈ [0,1] for AI-generated events (AION §19)
  - validation returns typed ValidationResult
  - EventSet: typed collection with bulk operations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, FrozenSet
import uuid

from .allen import Interval
from .types  import TypeHierarchy, default_hierarchy


# ── ValidationResult ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    is_valid: bool
    errors:   list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        if self.is_valid:
            return "ValidationResult(OK)"
        return f"ValidationResult(FAIL: {self.errors})"


# ── ClinicalEvent ─────────────────────────────────────────────────────────────

@dataclass
class ClinicalEvent:
    """
    AION §5.1: Clinical event 6-tuple  e = (p, a, τ, [t^B,t^E], α, ρ).

    patient_id  : str    — p ∈ P
    stay_id     : str    — a ∈ A_p
    type        : str    — τ ∈ T (TypeHierarchy node name)
    tau         : Interval — [t^B, t^E]
    attributes  : dict   — α: attribute assignments per σ(τ)
    refs        : frozenset[str] — ρ: IDs of reference (parent) events
    confidence  : float  — c ∈ [0,1]; 1.0 for deterministic events
    """
    patient_id:  str
    stay_id:     str
    type:        str
    tau:         Interval
    attributes:  dict[str, Any]            = field(default_factory=dict)
    refs:        FrozenSet[str]            = field(default_factory=frozenset)
    confidence:  float                     = 1.0

    def __post_init__(self) -> None:
        # Ensure refs is always a frozenset
        if not isinstance(self.refs, frozenset):
            object.__setattr__(self, "refs", frozenset(self.refs))
        # Auto-assign id if missing
        if "id" not in self.attributes:
            self.attributes["id"] = str(uuid.uuid4())
        # Clamp confidence
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be in [0,1], got {self.confidence}")

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self.attributes["id"]

    @property
    def t_begin(self) -> Any:
        return self.tau.start

    @property
    def t_end(self) -> Any:
        return self.tau.end

    @property
    def is_point_event(self) -> bool:
        return self.tau.is_point

    @property
    def is_ai_generated(self) -> bool:
        return self.confidence < 1.0

    # ── Validation (AION §5.2) ────────────────────────────────────────────────

    def validate(
        self,
        hierarchy:        Optional[TypeHierarchy] = None,
        stay_interval:    Optional[Interval] = None,
        all_event_ids:    Optional[set[str]] = None,
    ) -> ValidationResult:
        """
        Validate all four consistency conditions of AION §5.2.

        hierarchy      : TypeHierarchy to check type membership and schema
        stay_interval  : Interval of the associated stay (condition 1)
        all_event_ids  : set of known event IDs (condition 3)
        """
        h      = hierarchy or default_hierarchy()
        errors: list[str] = []

        # 1. Type membership
        if self.type not in h:
            errors.append(f"[TYPE] Unknown type '{self.type}'")

        # 2. Type schema: required attributes present
        schema_errors = h.validate_attrs(self.type, self.attributes)
        errors.extend(f"[SCHEMA] {e}" for e in schema_errors)

        # 3. Temporal embedding: [t^B, t^E] ⊆ stay
        if stay_interval is not None:
            if self.tau.start < stay_interval.start or self.tau.end > stay_interval.end:
                errors.append(
                    f"[TEMPORAL] Event [{self.tau.start}, {self.tau.end}] "
                    f"not contained in stay [{stay_interval.start}, {stay_interval.end}]"
                )

        # 4. Referential integrity: all ρ IDs must be known
        if all_event_ids is not None:
            missing = self.refs - all_event_ids
            if missing:
                errors.append(f"[REF] Unknown reference event IDs: {missing}")

        # 5. Confidence range (redundant due to __post_init__ but explicit)
        if not (0.0 <= self.confidence <= 1.0):
            errors.append(f"[CONF] Confidence {self.confidence} outside [0,1]")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors)

    # ── Type helpers ─────────────────────────────────────────────────────────

    def has_type(
        self, type_name: str, hierarchy: Optional[TypeHierarchy] = None
    ) -> bool:
        """True iff self.type ≺* type_name (subtype test, AION §10 HasType)."""
        h = hierarchy or default_hierarchy()
        return h.is_subtype(self.type, type_name)

    # ── Attribute helpers ─────────────────────────────────────────────────────

    def attr(self, name: str, default: Any = None) -> Any:
        return self.attributes.get(name, default)

    def with_attr(self, name: str, value: Any) -> "ClinicalEvent":
        """Return a new event with one attribute replaced (immutable update)."""
        new_attrs = {**self.attributes, name: value}
        return ClinicalEvent(
            patient_id=self.patient_id,
            stay_id=self.stay_id,
            type=self.type,
            tau=self.tau,
            attributes=new_attrs,
            refs=self.refs,
            confidence=self.confidence,
        )

    def with_confidence(self, c: float) -> "ClinicalEvent":
        return ClinicalEvent(
            patient_id=self.patient_id,
            stay_id=self.stay_id,
            type=self.type,
            tau=self.tau,
            attributes=dict(self.attributes),
            refs=self.refs,
            confidence=c,
        )

    def __repr__(self) -> str:
        return (
            f"ClinicalEvent(id={self.id!r}, type={self.type!r}, "
            f"tau={self.tau!r}, p={self.patient_id!r}, conf={self.confidence:.2f})"
        )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ClinicalEvent) and self.id == other.id


# ── EventSet ─────────────────────────────────────────────────────────────────

class EventSet:
    """
    AION §5: Typed, indexed collection of ClinicalEvent objects.

    E_τ  = {e ∈ E | type(e) = τ}
    E_≺τ = {e ∈ E | type(e) ≺* τ}

    Supports confidence filtering: E_{c_min} (AION §19).
    """

    def __init__(
        self,
        events:    Optional[list[ClinicalEvent]] = None,
        hierarchy: Optional[TypeHierarchy]       = None,
    ) -> None:
        self._h: TypeHierarchy = hierarchy or default_hierarchy()
        self._by_id:      dict[str, ClinicalEvent] = {}
        self._by_patient: dict[str, list[ClinicalEvent]] = {}
        self._by_type:    dict[str, list[ClinicalEvent]] = {}

        for e in (events or []):
            self.add(e)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add(self, event: ClinicalEvent) -> None:
        if event.id in self._by_id:
            raise ValueError(f"Duplicate event ID: {event.id!r}")
        self._by_id[event.id] = event
        self._by_patient.setdefault(event.patient_id, []).append(event)
        self._by_type.setdefault(event.type, []).append(event)

    def remove(self, event_id: str) -> None:
        if event_id not in self._by_id:
            raise KeyError(event_id)
        e = self._by_id.pop(event_id)
        self._by_patient[e.patient_id].remove(e)
        self._by_type[e.type].remove(e)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get(self, event_id: str) -> Optional[ClinicalEvent]:
        return self._by_id.get(event_id)

    def by_patient(self, patient_id: str) -> list[ClinicalEvent]:
        """All events of a patient, sorted by t_begin."""
        evts = self._by_patient.get(patient_id, [])
        return sorted(evts, key=lambda e: e.tau.start)

    def by_type_exact(self, type_name: str) -> list[ClinicalEvent]:
        """E_τ: exact type match."""
        return list(self._by_type.get(type_name, []))

    def by_type(self, type_name: str) -> list[ClinicalEvent]:
        """
        E_≺τ: all events whose type is a subtype of *type_name*.
        AION §5: E_{≺τ} = {e ∈ E | type(e) ≺* τ}
        """
        result: list[ClinicalEvent] = []
        for t, evts in self._by_type.items():
            if self._h.is_subtype(t, type_name):
                result.extend(evts)
        return sorted(result, key=lambda e: e.tau.start)

    def with_confidence(self, c_min: float) -> "EventSet":
        """
        E_{c_min}: accepted event set above confidence threshold (AION §19).
        Returns a new EventSet.
        """
        accepted = [e for e in self._by_id.values() if e.confidence >= c_min]
        return EventSet(accepted, self._h)

    def for_stay(self, stay_id: str) -> list[ClinicalEvent]:
        return [e for e in self._by_id.values() if e.stay_id == stay_id]

    def sequence(self, patient_id: str) -> list[ClinicalEvent]:
        """
        AION §11: Temporally ordered event sequence e_k = (e_{k,1}, ..., e_{k,n_k}).
        """
        return self.by_patient(patient_id)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_all(
        self,
        stay_intervals: Optional[dict[str, Interval]] = None,
    ) -> dict[str, ValidationResult]:
        """
        Validate all events. stay_intervals: {stay_id → Interval}.
        Returns {event_id → ValidationResult}.
        """
        all_ids = set(self._by_id.keys())
        results: dict[str, ValidationResult] = {}
        for eid, e in self._by_id.items():
            si = (stay_intervals or {}).get(e.stay_id)
            results[eid] = e.validate(
                hierarchy=self._h,
                stay_interval=si,
                all_event_ids=all_ids,
            )
        return results

    def is_consistent(
        self,
        stay_intervals: Optional[dict[str, Interval]] = None,
    ) -> bool:
        """True iff all events pass validation."""
        return all(self.validate_all(stay_intervals).values())

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def all_events(self) -> list[ClinicalEvent]:
        return list(self._by_id.values())

    @property
    def all_patients(self) -> set[str]:
        return set(self._by_patient.keys())

    @property
    def all_types(self) -> set[str]:
        return set(self._by_type.keys())

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, event_id: str) -> bool:
        return event_id in self._by_id

    def __iter__(self):
        return iter(self._by_id.values())

    def __repr__(self) -> str:
        return (
            f"EventSet({len(self)} events, "
            f"{len(self._by_patient)} patients, "
            f"{len(self._by_type)} types)"
        )
