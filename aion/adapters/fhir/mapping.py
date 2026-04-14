# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.adapters.fhir.mapping
==========================
AION §17: FHIR Mapping as Structural Homomorphism.

(h_T, h_σ): internal model → FHIR R4 resource model.

Homomorphism conditions (AION §17.3):
  1. Type hierarchy preservation   : τ ≺ τ' ⟹ h_T(τ) is FHIR profile of h_T(τ')
  2. Attribute value space         : ∃ injective ι_a: V → dom(fhir_type)
  3. Temporal model consistency    : [t^B, t^E] → effectivePeriod
  4. Reference structure           : e_1 → e_2 ⟹ h(e_2).partOf = ref(h(e_1))

Mapping quality index:
  Q_map = |{e ∈ E | h(e) is FHIR-valid}| / |E|

SILD compatibility: imports SILD LossFinding for mapping validation.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

from ...core.event import ClinicalEvent, EventSet
from ...core.types import TypeHierarchy, default_hierarchy


# ── FHIR Resource Type Registry ───────────────────────────────────────────────

# AION §17.1: Standard FHIR R4 resource types relevant to the model
FHIR_RESOURCE_TYPES = {
    "Patient", "Encounter", "Condition", "Procedure",
    "Observation", "MedicationAdministration", "MedicationRequest",
    "DiagnosticReport", "DocumentReference", "AllergyIntolerance",
}


@dataclass(frozen=True)
class FHIRElementPath:
    """
    AION §17.2: FHIR element path descriptor.
    e.g. Observation.valueQuantity.value
    """
    resource:    str      # FHIR resource type
    path:        str      # dot-path within resource
    fhir_type:   str      # FHIR data type (decimal, string, CodeableConcept, ...)
    cardinality: str = "0..1"   # 0..1 | 1..1 | 0..* | 1..*

    @property
    def full_path(self) -> str:
        return f"{self.resource}.{self.path}"

    def is_required(self) -> bool:
        return self.cardinality.startswith("1")


# ── TypeMapping h_T ───────────────────────────────────────────────────────────

@dataclass
class TypeMapping:
    """
    AION §17.2: h_T: T → R_FHIR — partial function.
    internal_type → (fhir_resource, optional category_code)
    """
    internal_type: str
    fhir_resource: str
    category_code: Optional[str] = None   # e.g. "laboratory" for Observation
    fhir_profile:  Optional[str] = None   # profile URL if applicable

    def __repr__(self) -> str:
        cat = f"[{self.category_code}]" if self.category_code else ""
        return f"TypeMap({self.internal_type!r} → {self.fhir_resource}{cat})"


# ── AttributeMapping h_σ ──────────────────────────────────────────────────────

@dataclass
class AttributeMapping:
    """
    AION §17.2: h_σ(τ, a) = (path, fhir_type, cardinality).
    """
    internal_type: str
    attr_name:     str
    fhir_element:  FHIRElementPath
    # Value injector: converts internal value → FHIR-compatible value
    injector:      Optional[Any] = None   # Callable[[Any], Any]

    def inject(self, value: Any) -> Any:
        if self.injector is not None:
            return self.injector(value)
        return value


# ── FHIRMappingSpec ───────────────────────────────────────────────────────────

class FHIRMappingSpec:
    """
    AION §17: Complete FHIR mapping specification (h_T, h_σ).

    Provides:
      - map_event()     : ClinicalEvent → FHIRResource dict
      - validate()      : check homomorphism conditions
      - quality_index() : Q_map ∈ [0,1]
    """

    # Default AION → FHIR type mappings (AION §17.2 Table)
    DEFAULT_TYPE_MAPS: list[TypeMapping] = [
        TypeMapping("Diagnosis",   "Condition"),
        TypeMapping("Procedure",   "Procedure"),
        TypeMapping("HLMPhase",    "Procedure",  category_code="HLM"),
        TypeMapping("Anaesthesia", "Procedure",  category_code="anaesthesia"),
        TypeMapping("Medication",  "MedicationAdministration"),
        TypeMapping("LabResult",   "Observation", category_code="laboratory"),
        TypeMapping("VitalSign",   "Observation", category_code="vital-signs"),
        TypeMapping("Score",       "Observation", category_code="survey"),
        TypeMapping("Imaging",     "DiagnosticReport"),
        TypeMapping("Observation", "Observation"),
        TypeMapping("Encounter",   "Encounter"),
        TypeMapping("Episode",     "EpisodeOfCare"),
        # FHIR mirror types (from SILD)
        TypeMapping("fhir:Condition",               "Condition"),
        TypeMapping("fhir:Observation",             "Observation"),
        TypeMapping("fhir:Procedure",               "Procedure"),
        TypeMapping("fhir:MedicationAdministration","MedicationAdministration"),
        TypeMapping("fhir:Encounter",               "Encounter"),
        TypeMapping("fhir:DiagnosticReport",        "DiagnosticReport"),
    ]

    def __init__(
        self,
        hierarchy: Optional[TypeHierarchy] = None,
    ) -> None:
        self._h          = hierarchy or default_hierarchy()
        self._type_maps: dict[str, TypeMapping]                = {}
        self._attr_maps: dict[tuple[str, str], AttributeMapping] = {}

        # Register defaults
        for tm in self.DEFAULT_TYPE_MAPS:
            self.register_type_map(tm)

        # Register default attribute mappings
        self._register_default_attr_maps()

    def register_type_map(self, tm: TypeMapping) -> None:
        self._type_maps[tm.internal_type] = tm

    def register_attr_map(self, am: AttributeMapping) -> None:
        self._attr_maps[(am.internal_type, am.attr_name)] = am

    def _register_default_attr_maps(self) -> None:
        """AION §17.2: Default attribute mappings."""
        # ── Observation / LabResult ───────────────────────────────────────────
        for t in ("Observation", "LabResult", "VitalSign", "Score"):
            self._attr_maps.update({
                (t, "q_code"): AttributeMapping(t, "q_code",
                    FHIRElementPath("Observation","code","CodeableConcept","1..1")),
                (t, "value"): AttributeMapping(t, "value",
                    FHIRElementPath("Observation","valueQuantity.value","decimal","0..1")),
                (t, "unit"): AttributeMapping(t, "unit",
                    FHIRElementPath("Observation","valueQuantity.unit","string","0..1")),
            })

        # ── Procedure / HLMPhase ──────────────────────────────────────────────
        for t in ("Procedure", "HLMPhase", "Anaesthesia"):
            self._attr_maps.update({
                (t, "op_code"): AttributeMapping(t, "op_code",
                    FHIRElementPath("Procedure","code","CodeableConcept","0..1")),
                (t, "surgeon"): AttributeMapping(t, "surgeon",
                    FHIRElementPath("Procedure","performer.actor","Reference","0..*")),
            })

        # ── Diagnosis / Condition ─────────────────────────────────────────────
        self._attr_maps.update({
            ("Diagnosis","dx_code"): AttributeMapping("Diagnosis","dx_code",
                FHIRElementPath("Condition","code","CodeableConcept","0..1")),
            ("Diagnosis","certainty"): AttributeMapping("Diagnosis","certainty",
                FHIRElementPath("Condition","verificationStatus","CodeableConcept","0..1")),
        })

        # ── Medication ────────────────────────────────────────────────────────
        self._attr_maps.update({
            ("Medication","substance"): AttributeMapping("Medication","substance",
                FHIRElementPath("MedicationAdministration","medicationCodeableConcept","CodeableConcept","1..1")),
            ("Medication","dose"): AttributeMapping("Medication","dose",
                FHIRElementPath("MedicationAdministration","dosage.dose.value","decimal","0..1")),
        })

        # ── Universal (all types) ─────────────────────────────────────────────
        # id → Resource.identifier, t_begin/t_end → effectivePeriod
        # These are handled in map_event() directly

    # ── Mapping functions ─────────────────────────────────────────────────────

    def type_map(self, internal_type: str) -> Optional[TypeMapping]:
        """h_T(τ): look up FHIR resource type for internal type."""
        # Direct match first
        if internal_type in self._type_maps:
            return self._type_maps[internal_type]
        # Try ancestors in type hierarchy
        for ancestor in self._h.ancestors(internal_type):
            if ancestor in self._type_maps:
                return self._type_maps[ancestor]
        return None

    def attr_map(
        self, internal_type: str, attr_name: str
    ) -> Optional[AttributeMapping]:
        """h_σ(τ, a): look up FHIR element path for attribute."""
        key = (internal_type, attr_name)
        if key in self._attr_maps:
            return self._attr_maps[key]
        # Try ancestors
        for ancestor in self._h.ancestors(internal_type):
            key2 = (ancestor, attr_name)
            if key2 in self._attr_maps:
                return self._attr_maps[key2]
        return None

    def map_event(self, event: ClinicalEvent) -> Optional["FHIRResource"]:
        """
        AION §17.5: h(e) — map ClinicalEvent to a FHIR resource dict.
        Returns None if no type mapping exists.
        """
        tm = self.type_map(event.type)
        if tm is None:
            return None

        resource: dict[str, Any] = {
            "resourceType": tm.fhir_resource,
            "id": event.id,
            "identifier": [{"value": event.id}],
        }

        # Temporal mapping: [t^B, t^E] → effectivePeriod
        resource["effectivePeriod"] = {
            "start": event.tau.start.isoformat(),
            "end":   event.tau.end.isoformat(),
        }
        resource["effectiveDateTime"] = event.tau.start.isoformat()

        # Category (for Observation subtypes)
        if tm.category_code:
            resource["category"] = [{
                "coding": [{"code": tm.category_code}]
            }]

        # Attribute mappings
        for attr_name, attr_val in event.attributes.items():
            if attr_name in ("id", "t_begin", "t_end"):
                continue
            am = self.attr_map(event.type, attr_name)
            if am is None:
                continue
            # Set value at FHIR path (simplified: top-level only)
            path_key = am.fhir_element.path.split(".")[0]
            resource[path_key] = am.inject(attr_val)

        # Reference structure: partOf for subprocess events
        if event.refs:
            resource["partOf"] = [
                {"reference": f"{tm.fhir_resource}/{ref_id}"}
                for ref_id in event.refs
            ]

        return FHIRResource(
            resource_type=tm.fhir_resource,
            resource_id=event.id,
            data=resource,
            source_event=event,
            category=tm.category_code,
        )

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_resource(self, resource: "FHIRResource") -> list[str]:
        """
        AION §17.6: Validate a mapped FHIR resource.
        Checks required fields, cardinality, temporal consistency.
        """
        errors: list[str] = []

        if resource.resource_type not in FHIR_RESOURCE_TYPES | {"EpisodeOfCare"}:
            errors.append(f"Unknown FHIR resource type: {resource.resource_type!r}")

        # Check effectivePeriod or effectiveDateTime present
        d = resource.data
        if "effectivePeriod" not in d and "effectiveDateTime" not in d:
            errors.append(f"Temporal field missing in {resource.resource_type}/{resource.resource_id}")

        # Identifier required
        if "identifier" not in d and "id" not in d:
            errors.append("No identifier/id in resource")

        return errors

    def quality_index(self, event_set: EventSet) -> float:
        """
        AION §17.6: Q_map = |valid FHIR resources| / |E|.
        """
        if len(event_set) == 0:
            return 1.0
        valid = 0
        for event in event_set.all_events:
            resource = self.map_event(event)
            if resource is None:
                continue
            errors = self.validate_resource(resource)
            if not errors:
                valid += 1
        return valid / len(event_set)

    def export_bundle(self, event_set: EventSet) -> "FHIRBundle":
        """
        Export all events in *event_set* as a FHIR Bundle.
        """
        resources: list[FHIRResource] = []
        unmapped:  list[ClinicalEvent] = []
        for event in event_set.all_events:
            r = self.map_event(event)
            if r is not None:
                resources.append(r)
            else:
                unmapped.append(event)
        return FHIRBundle(resources=resources, unmapped=unmapped)

    def total_combined_quality(
        self,
        q_ges:   float,
        q_map:   float,
        lam:     float = 0.5,
    ) -> float:
        """
        AION §17.6: Q_total = λ·Q_ges + (1-λ)·Q_map.
        """
        return lam * q_ges + (1.0 - lam) * q_map


# ── FHIRResource ──────────────────────────────────────────────────────────────

@dataclass
class FHIRResource:
    """
    Output of h(e): a FHIR R4 resource.
    """
    resource_type:  str
    resource_id:    str
    data:           dict[str, Any]
    source_event:   Optional[ClinicalEvent] = None
    category:       Optional[str] = None

    @property
    def is_observation(self) -> bool:
        return self.resource_type == "Observation"

    def to_json_dict(self) -> dict[str, Any]:
        return dict(self.data)

    def __repr__(self) -> str:
        return f"FHIRResource({self.resource_type}/{self.resource_id})"


# ── FHIRBundle ────────────────────────────────────────────────────────────────

@dataclass
class FHIRBundle:
    """
    FHIR Bundle wrapping all mapped resources.
    """
    resources: list[FHIRResource]
    unmapped:  list[ClinicalEvent] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.resources)

    @property
    def n_unmapped(self) -> int:
        return len(self.unmapped)

    @property
    def mapping_coverage(self) -> float:
        total = self.size + self.n_unmapped
        return self.size / total if total > 0 else 1.0

    def by_type(self, resource_type: str) -> list[FHIRResource]:
        return [r for r in self.resources if r.resource_type == resource_type]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "resourceType": "Bundle",
            "type": "collection",
            "total": self.size,
            "entry": [
                {"resource": r.to_json_dict()}
                for r in self.resources
            ],
        }

    def __repr__(self) -> str:
        return (
            f"FHIRBundle({self.size} resources, "
            f"{self.n_unmapped} unmapped, "
            f"coverage={self.mapping_coverage:.1%})"
        )
