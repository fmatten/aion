# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.ai.component
=================
AION §19: AI Components as a Formal Model.

Every AI component is a 5-tuple:
    A_l = (X_l, Y_l, f_θ, L, θ*)

    X_l  : input space (Layer l)
    Y_l  : output space (Layer l)
    f_θ  : X_l → Δ(Y_l)  parametrised stochastic mapping
    L    : Δ(Y_l) × Y_l → ℝ≥0  loss function
    θ*   : argmin_θ E[L(f_θ(x), y)]  optimal parameters

All outputs pass through a validation operator Π_l before entering EventSet.

Layer catalogue (AION §19.4–§19.8):
    Layer 2 — Event extraction from free text         X=Σ*, Y=Ê
    Layer 3a — Episode parameter estimation           X=T×ℝ^d, Y=ℝ>0
    Layer 3b — Trajectory prediction                  X=E^m, Y=Δ(T×ℝ≥0)
    Layer 4  — Natural language query translation     X=Σ*, Y=Φ(S)
    Layer 5  — Risk estimation                        X=ℝ^d, Y=[0,1]
    Val.     — Soft rule learning                     X=E_τ, Y=[0,1]
"""

from __future__ import annotations

import uuid
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

from ..core.event import ClinicalEvent, EventSet, ValidationResult
from ..core.types import TypeHierarchy, default_hierarchy
from ..core.allen import Interval

# Type variables for input/output spaces
X = TypeVar("X")
Y = TypeVar("Y")


# ── AIOutput ──────────────────────────────────────────────────────────────────

@dataclass
class AIOutput(Generic[Y]):
    """
    Wrapper for AI component output with confidence.
    y         : the actual output value
    confidence: c ∈ [0,1]
    component : which component produced this
    metadata  : optional provenance info
    """
    value:      Y
    confidence: float
    component:  str = ""
    metadata:   dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be in [0,1], got {self.confidence}")

    def __repr__(self) -> str:
        return (
            f"AIOutput(conf={self.confidence:.2f}, "
            f"component={self.component!r})"
        )


# ── ValidationOperator Π_l ────────────────────────────────────────────────────

@dataclass
class ValidationDecision:
    """
    Result of Π_l(y): accepted or rejected.
    accepted    : True → y is incorporated; False → ⊥
    reason      : why rejected (if applicable)
    errors      : detailed validation errors
    """
    accepted:   bool
    reason:     str = ""
    errors:     list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.accepted

    def __repr__(self) -> str:
        status = "ACCEPTED" if self.accepted else f"REJECTED({self.reason})"
        return f"ValidationDecision({status})"


class ValidationOperator:
    """
    AION §19.2: Π_l — gate before AI output enters the formal model.

    Π_l(y) = y   if all consistency and type conditions satisfied
    Π_l(y) = ⊥   otherwise

    Configurable via:
      c_min       : minimum confidence threshold
      custom_checks: additional domain-specific validators
    """

    def __init__(
        self,
        layer:         int,
        c_min:         float = 0.0,
        custom_checks: Optional[list[Callable[[Any], list[str]]]] = None,
    ) -> None:
        self.layer         = layer
        self.c_min         = c_min
        self.custom_checks = custom_checks or []

    def validate(self, output: AIOutput) -> ValidationDecision:
        """Run all validation checks on an AI output."""
        errors: list[str] = []

        # 1. Confidence threshold
        if output.confidence < self.c_min:
            return ValidationDecision(
                accepted=False,
                reason="confidence_too_low",
                errors=[f"Confidence {output.confidence:.3f} < c_min {self.c_min:.3f}"],
            )

        # 2. Custom domain checks
        for check in self.custom_checks:
            errs = check(output.value)
            errors.extend(errs)

        if errors:
            return ValidationDecision(
                accepted=False, reason="domain_check_failed", errors=errors
            )
        return ValidationDecision(accepted=True)

    def __repr__(self) -> str:
        return f"ValidationOperator(layer={self.layer}, c_min={self.c_min})"


# ── AIComponent Base ──────────────────────────────────────────────────────────

class AIComponent(ABC, Generic[X, Y]):
    """
    AION §19.1: Abstract base for all AI components.

    A_l = (X_l, Y_l, f_θ, L, θ*) + Π_l (validation operator).
    """

    def __init__(
        self,
        layer:     int,
        name:      str,
        validator: Optional[ValidationOperator] = None,
    ) -> None:
        self.layer     = layer
        self.name      = name
        self.validator = validator or ValidationOperator(layer)

    @abstractmethod
    def predict(self, x: X) -> AIOutput[Y]:
        """f_θ(x) → AIOutput containing y ∼ Δ(Y_l)."""
        ...

    def validate(self, output: AIOutput[Y]) -> ValidationDecision:
        """Π_l(output)."""
        return self.validator.validate(output)

    def predict_and_validate(self, x: X) -> tuple[Optional[Y], ValidationDecision]:
        """
        Combined: predict then validate.
        Returns (y, decision). y is None if rejected.
        """
        output   = self.predict(x)
        decision = self.validate(output)
        if decision.accepted:
            return output.value, decision
        return None, decision

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(layer={self.layer}, name={self.name!r})"


# ══════════════════════════════════════════════════════════════════════════════
# Layer 2: Event Extraction from Free Text (AION §19.4)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractedEvent:
    """
    Output of Layer-2 extraction: partially constructed clinical event.
    Fields may be None if the extractor is uncertain.
    """
    patient_id:  str
    stay_id:     str
    type_name:   str
    t_begin:     Optional[datetime.datetime]
    t_end:       Optional[datetime.datetime]
    attributes:  dict[str, Any]
    source_text: str = ""

    def to_clinical_event(
        self,
        hierarchy: Optional[TypeHierarchy] = None,
        confidence: float = 1.0,
    ) -> Optional[ClinicalEvent]:
        """
        Materialise into a ClinicalEvent if temporal data is complete.
        Returns None if t_begin is missing.
        """
        if self.t_begin is None:
            return None
        t_end = self.t_end or self.t_begin
        try:
            return ClinicalEvent(
                patient_id=self.patient_id,
                stay_id=self.stay_id,
                type=self.type_name,
                tau=Interval(self.t_begin, t_end),
                attributes=self.attributes,
                confidence=confidence,
            )
        except Exception:
            return None


class EventExtractionComponent(AIComponent[str, ExtractedEvent]):
    """
    AION §19.4: Layer-2 AI Component — event extraction from free text.

    f_θ^(2) : Σ* → Δ(Ê)
    X_2 = Σ*  (strings)
    Y_2 = Ê   (confidence-weighted event set)

    This base class provides the interface; concrete implementations
    (rule-based, NER-based, LLM-based) override _extract().
    """

    def __init__(
        self,
        hierarchy: Optional[TypeHierarchy] = None,
        c_min:     float = 0.9,
    ) -> None:
        hierarchy = hierarchy or default_hierarchy()
        validator = ValidationOperator(
            layer=2,
            c_min=c_min,
            custom_checks=[
                self._check_type_known_factory(hierarchy),
                self._check_temporal_present,
            ],
        )
        super().__init__(layer=2, name="EventExtraction", validator=validator)
        self._h = hierarchy

    @staticmethod
    def _check_type_known_factory(h: TypeHierarchy):
        def check(extracted: ExtractedEvent) -> list[str]:
            if extracted.type_name not in h:
                return [f"Unknown event type: {extracted.type_name!r}"]
            return []
        return check

    @staticmethod
    def _check_temporal_present(extracted: ExtractedEvent) -> list[str]:
        if extracted.t_begin is None:
            return ["TEMPORAL_LOSS: no_datetime — t_begin could not be extracted"]
        return []

    def predict(self, text: str) -> AIOutput[ExtractedEvent]:
        """Override in concrete implementations."""
        extracted, confidence = self._extract(text)
        return AIOutput(
            value=extracted,
            confidence=confidence,
            component=self.name,
            metadata={"source_text_len": len(text)},
        )

    def _extract(self, text: str) -> tuple[ExtractedEvent, float]:
        """
        Override to implement actual extraction logic.
        Default: returns a dummy extraction with low confidence.
        """
        return ExtractedEvent(
            patient_id="",
            stay_id="",
            type_name="Observation",
            t_begin=None,
            t_end=None,
            attributes={},
            source_text=text,
        ), 0.0

    def extract_to_event_set(
        self,
        texts:      list[tuple[str, str, str]],  # (text, patient_id, stay_id)
        event_set:  EventSet,
    ) -> tuple[int, int]:
        """
        Extract from multiple texts and add accepted events to *event_set*.
        Returns (n_accepted, n_rejected).
        """
        accepted = 0
        rejected = 0
        for text, pid, sid in texts:
            output   = self.predict(text)
            decision = self.validate(output)
            if not decision:
                rejected += 1
                continue
            extracted = output.value
            extracted.patient_id = pid
            extracted.stay_id    = sid
            ce = extracted.to_clinical_event(self._h, output.confidence)
            if ce is not None:
                try:
                    event_set.add(ce)
                    accepted += 1
                except ValueError:
                    rejected += 1
            else:
                rejected += 1
        return accepted, rejected


# ══════════════════════════════════════════════════════════════════════════════
# Layer 5: Risk Estimation (AION §19.7)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PatientFeatureVector:
    """
    AION §19.7: Ψ(p_k) ∈ ℝ^d — feature vector for risk estimation.
    Built from EventSet aggregates.
    """
    patient_id: str
    features:   dict[str, float]   # name → value

    def to_list(self, feature_names: list[str]) -> list[float]:
        return [self.features.get(n, 0.0) for n in feature_names]

    def __repr__(self) -> str:
        return (
            f"PatientFeatureVector(p={self.patient_id!r}, "
            f"d={len(self.features)})"
        )


class FeatureExtractor:
    """
    AION §19.7: Ψ: P → ℝ^d — extracts feature vectors from EventSet.

    Standard features:
      - count_<type>  : number of events of each type
      - mean_<attr>   : mean attribute value
      - max_<attr>    : max attribute value
      - has_<type>    : binary indicator
    """

    def __init__(
        self,
        type_names:  list[str],
        attr_aggs:   Optional[list[tuple[str, str, str]]] = None,
        hierarchy:   Optional[TypeHierarchy] = None,
    ) -> None:
        """
        type_names  : types to compute count_ and has_ features for
        attr_aggs   : list of (type_name, attr_name, agg) e.g. ("LabResult","value","mean")
        """
        self.type_names = type_names
        self.attr_aggs  = attr_aggs or []
        self._h         = hierarchy or default_hierarchy()

    def extract(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> PatientFeatureVector:
        """Build Ψ(p_k) from event_set."""
        features: dict[str, float] = {}
        evts = event_set.by_patient(patient_id)

        for type_name in self.type_names:
            typed = [
                e for e in evts
                if self._h.is_subtype(e.type, type_name)
            ]
            features[f"count_{type_name}"] = float(len(typed))
            features[f"has_{type_name}"]   = 1.0 if typed else 0.0

        for (type_name, attr_name, agg) in self.attr_aggs:
            typed = [
                e for e in evts
                if self._h.is_subtype(e.type, type_name)
            ]
            values = [
                e.attr(attr_name) for e in typed
                if isinstance(e.attr(attr_name), (int, float))
            ]
            if not values:
                features[f"{agg}_{type_name}_{attr_name}"] = 0.0
            elif agg == "mean":
                features[f"mean_{type_name}_{attr_name}"] = sum(values) / len(values)
            elif agg == "max":
                features[f"max_{type_name}_{attr_name}"] = max(values)
            elif agg == "min":
                features[f"min_{type_name}_{attr_name}"] = min(values)
            elif agg == "sum":
                features[f"sum_{type_name}_{attr_name}"] = sum(values)
            elif agg == "count":
                features[f"count_{type_name}_{attr_name}"] = float(len(values))

        return PatientFeatureVector(patient_id=patient_id, features=features)

    def extract_all(self, event_set: EventSet) -> dict[str, PatientFeatureVector]:
        return {
            pid: self.extract(pid, event_set)
            for pid in event_set.all_patients
        }

    @property
    def feature_names(self) -> list[str]:
        names = []
        for t in self.type_names:
            names += [f"count_{t}", f"has_{t}"]
        for (t, a, agg) in self.attr_aggs:
            names.append(f"{agg}_{t}_{a}")
        return names


class RiskEstimationComponent(AIComponent[PatientFeatureVector, float]):
    """
    AION §19.7: Layer-5 AI Component — risk estimation.

    f_θ^(5) : ℝ^d → [0,1]
    X_5 = ℝ^d (feature vector)
    Y_5 = [0,1] (risk probability)

    Calibration condition:
        E[p_k ∈ E | f_θ^(5)(Ψ(p_k)) = r] = r  for all r ∈ [0,1]
    """

    def __init__(
        self,
        model_fn:  Callable[[list[float]], float],
        feature_names: list[str],
        c_min:     float = 0.0,
    ) -> None:
        """
        model_fn      : feature_list → probability ∈ [0,1]
        feature_names : ordered list of feature names (for Ψ.to_list())
        """
        validator = ValidationOperator(
            layer=5,
            c_min=c_min,
            custom_checks=[self._check_probability_range],
        )
        super().__init__(layer=5, name="RiskEstimation", validator=validator)
        self.model_fn      = model_fn
        self.feature_names = feature_names

    @staticmethod
    def _check_probability_range(value: float) -> list[str]:
        if not (0.0 <= value <= 1.0):
            return [f"Risk estimate {value:.4f} outside [0,1]"]
        return []

    def predict(self, fv: PatientFeatureVector) -> AIOutput[float]:
        features = fv.to_list(self.feature_names)
        risk     = float(self.model_fn(features))
        risk     = max(0.0, min(1.0, risk))   # clamp
        return AIOutput(
            value=risk,
            confidence=1.0,   # deterministic model
            component=self.name,
            metadata={"patient_id": fv.patient_id},
        )

    def estimate_cohort(
        self,
        feature_vectors: dict[str, PatientFeatureVector],
    ) -> dict[str, float]:
        """Estimate risk for all patients. Returns {patient_id → risk}."""
        result = {}
        for pid, fv in feature_vectors.items():
            output   = self.predict(fv)
            decision = self.validate(output)
            if decision.accepted:
                result[pid] = output.value
        return result


# ══════════════════════════════════════════════════════════════════════════════
# Confidence-weighted EventSet integration (AION §19.3)
# ══════════════════════════════════════════════════════════════════════════════

class AIEventIntegrator:
    """
    AION §19.3: Integrate AI-generated events into EventSet with c_min gate.

    Ê = {(e, c) | e ∈ E, c ∈ [0,1]}
    E_{c_min} = {e | (e,c) ∈ Ê, c ≥ c_min}
    """

    def __init__(
        self,
        event_set:  EventSet,
        c_min:      float = 0.9,
        hierarchy:  Optional[TypeHierarchy] = None,
    ) -> None:
        self.event_set = event_set
        self.c_min     = c_min
        self._h        = hierarchy or default_hierarchy()
        self._pending:  list[tuple[ClinicalEvent, float]] = []   # (event, confidence)
        self._accepted: int = 0
        self._rejected: int = 0

    def submit(
        self,
        event:      ClinicalEvent,
        confidence: float,
        stay_interval: Optional[Interval] = None,
    ) -> ValidationDecision:
        """
        Submit an AI-generated event for validation and potential integration.
        """
        # Validate the event itself
        vr = event.validate(
            hierarchy=self._h,
            stay_interval=stay_interval,
        )
        if not vr.is_valid:
            self._rejected += 1
            return ValidationDecision(
                accepted=False,
                reason="event_validation_failed",
                errors=vr.errors,
            )

        # Confidence gate
        if confidence < self.c_min:
            self._pending.append((event, confidence))
            self._rejected += 1
            return ValidationDecision(
                accepted=False,
                reason="confidence_below_threshold",
                errors=[f"c={confidence:.3f} < c_min={self.c_min:.3f}"],
            )

        # Accept: add to event set with confidence stamped
        accepted_event = event.with_confidence(confidence)
        try:
            self.event_set.add(accepted_event)
            self._accepted += 1
            return ValidationDecision(accepted=True)
        except ValueError as e:
            self._rejected += 1
            return ValidationDecision(
                accepted=False, reason="duplicate_id", errors=[str(e)]
            )

    @property
    def n_accepted(self) -> int:
        return self._accepted

    @property
    def n_rejected(self) -> int:
        return self._rejected

    @property
    def acceptance_rate(self) -> float:
        total = self._accepted + self._rejected
        return self._accepted / total if total > 0 else 0.0

    def __repr__(self) -> str:
        return (
            f"AIEventIntegrator("
            f"c_min={self.c_min}, "
            f"accepted={self._accepted}, "
            f"rejected={self._rejected})"
        )
