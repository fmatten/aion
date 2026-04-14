# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.core.types
===============
AION §3: Type System and Type Hierarchy.

Key additions over SILD TypeHierarchy:
  - AttributeSchema σ(τ) with Obligateness (required / optional)
  - Schema inheritance: τ ≺ τ' → σ(τ) ⊇ σ(τ')
  - TypeDef bundles type metadata with its schema
  - CompositionSchema comp(τ) ⊆ 2^T (which subtypes may be subprocesses)
  - Type-system-level validation (attribute completeness check)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union
import networkx as nx


# ── Obligateness ──────────────────────────────────────────────────────────────

class Obligateness(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


# ── AttributeDef ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AttributeDef:
    """
    AION §3.3: Single attribute descriptor (a_j, V_j, m_j) ∈ σ(τ).

    name        : attribute name (key used in ClinicalEvent.attributes)
    value_type  : Python type or type name string for documentation
    obligateness: required | optional
    description : human-readable documentation
    """
    name:         str
    value_type:   Union[type, str]   # e.g. float, str, "ICD10Code"
    obligateness: Obligateness = Obligateness.OPTIONAL
    description:  str = ""

    @property
    def is_required(self) -> bool:
        return self.obligateness == Obligateness.REQUIRED


# ── AttributeSchema σ(τ) ─────────────────────────────────────────────────────

class AttributeSchema:
    """
    AION §3.3: Attribute schema σ(τ) = set of AttributeDef.

    Implements schema inheritance:
        τ ≺ τ'  →  σ(τ) ⊇ σ(τ')
    i.e. a subtype inherits ALL attributes of its supertype and may add more.
    """

    # Root schema σ(⊤): every clinical event has these attributes.
    # Note: t_begin / t_end are OPTIONAL here because the canonical temporal
    # representation is the ClinicalEvent.tau (Interval) field — attributes
    # may mirror them for SQL/FHIR export but are not required in-memory.
    _ROOT_ATTRS: list[AttributeDef] = [
        AttributeDef("id",      str,   Obligateness.REQUIRED, "Globally unique event identifier"),
        AttributeDef("t_begin", float, Obligateness.OPTIONAL, "Start timestamp (mirrors tau.start)"),
        AttributeDef("t_end",   float, Obligateness.OPTIONAL, "End timestamp (mirrors tau.end)"),
    ]

    def __init__(self, own: Optional[list[AttributeDef]] = None) -> None:
        # own attributes defined directly for this type (not inherited)
        self._own: list[AttributeDef] = own or []

    # ── Schema operations ────────────────────────────────────────────────────

    def union(self, parent: "AttributeSchema") -> "AttributeSchema":
        """Return σ(self) ∪ σ(parent) — the inherited schema."""
        merged_names = {a.name for a in self._own}
        inherited = [a for a in parent.all_attrs if a.name not in merged_names]
        return AttributeSchema(own=self._own + inherited)

    @property
    def all_attrs(self) -> list[AttributeDef]:
        return self._own

    @property
    def required_attrs(self) -> list[AttributeDef]:
        return [a for a in self._own if a.is_required]

    @property
    def optional_attrs(self) -> list[AttributeDef]:
        return [a for a in self._own if not a.is_required]

    def contains(self, name: str) -> bool:
        return any(a.name == name for a in self._own)

    def get(self, name: str) -> Optional[AttributeDef]:
        return next((a for a in self._own if a.name == name), None)

    def validate_instance(self, attrs: dict[str, Any]) -> list[str]:
        """
        Validate an attribute dict against this schema.
        Returns list of error strings (empty = valid).
        """
        errors: list[str] = []
        for attr in self.required_attrs:
            if attr.name not in attrs or attrs[attr.name] is None:
                errors.append(f"Required attribute '{attr.name}' is missing or None")
        return errors

    def is_subschema_of(self, other: "AttributeSchema") -> bool:
        """
        AION §3.3: σ(self) ⊇ σ(other)  (self has at least all attrs of other).
        """
        other_names = {a.name for a in other.all_attrs}
        self_names  = {a.name for a in self.all_attrs}
        return other_names.issubset(self_names)

    def __repr__(self) -> str:
        names = [a.name for a in self._own]
        return f"AttributeSchema({names})"


# ── Built-in schemas ──────────────────────────────────────────────────────────

def _root_schema() -> AttributeSchema:
    return AttributeSchema(own=list(AttributeSchema._ROOT_ATTRS))


def _obs_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("q_code", str,   Obligateness.REQUIRED, "Observation code (LOINC, SNOMED, local)"),
        AttributeDef("value",  Any,   Obligateness.REQUIRED, "Observed value in V_q"),
        AttributeDef("unit",   str,   Obligateness.OPTIONAL, "Unit of measure (UCUM)"),
    ])


def _op_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("op_code",  str, Obligateness.REQUIRED, "Procedure code (OPS, SNOMED)"),
        AttributeDef("surgeon",  str, Obligateness.OPTIONAL, "Performing clinician"),
        AttributeDef("approach", str, Obligateness.OPTIONAL, "open | mininv | endosc"),
    ])


def _dx_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("dx_code",  str, Obligateness.REQUIRED, "Diagnosis code (ICD-10, ICD-11)"),
        AttributeDef("certainty", str, Obligateness.OPTIONAL, "confirmed | suspected | ruled_out"),
    ])


def _med_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("substance", str,   Obligateness.REQUIRED, "ATC code or substance name"),
        AttributeDef("dose",      float, Obligateness.OPTIONAL, "Dose amount"),
        AttributeDef("dose_unit", str,   Obligateness.OPTIONAL, "Dose unit (UCUM)"),
        AttributeDef("route",     str,   Obligateness.OPTIONAL, "iv | oral | sc | ..."),
    ])


def _lab_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("q_code",     str,   Obligateness.REQUIRED, "LOINC code"),
        AttributeDef("value",      float, Obligateness.REQUIRED, "Numeric result"),
        AttributeDef("unit",       str,   Obligateness.OPTIONAL, "UCUM unit"),
        AttributeDef("ref_min",    float, Obligateness.OPTIONAL, "Reference range lower bound"),
        AttributeDef("ref_max",    float, Obligateness.OPTIONAL, "Reference range upper bound"),
    ])


def _score_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("score_name",  str,   Obligateness.REQUIRED, "e.g. EuroSCORE_II, APACHE_II"),
        AttributeDef("score_value", float, Obligateness.REQUIRED, "Numeric score"),
        AttributeDef("risk_pct",    float, Obligateness.OPTIONAL, "Derived risk percentage"),
    ])


def _img_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("modality",  str, Obligateness.REQUIRED, "CT | MRI | Echo | XR | ..."),
        AttributeDef("body_site", str, Obligateness.OPTIONAL, "SNOMED body site"),
        AttributeDef("report",    str, Obligateness.OPTIONAL, "Free-text radiologist report"),
    ])


def _hlm_schema() -> AttributeSchema:
    return AttributeSchema(own=AttributeSchema._ROOT_ATTRS + [
        AttributeDef("flow",    float, Obligateness.OPTIONAL, "Pump flow (L/min)"),
        AttributeDef("pressure", float, Obligateness.OPTIONAL, "Arterial pressure (mmHg)"),
        AttributeDef("temp",    float, Obligateness.OPTIONAL, "Blood temperature (°C)"),
    ])


# ── TypeDef ──────────────────────────────────────────────────────────────────

@dataclass
class TypeDef:
    """
    Complete definition of a clinical event type τ ∈ T.
    Bundles the type name, its schema, and composition rules.
    """
    name:        str
    parent:      Optional[str]         # None only for ⊤
    schema:      AttributeSchema       # σ(τ) — inherited schema already merged in
    label:       str = ""
    description: str = ""

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TypeDef) and self.name == other.name


# ── TypeHierarchy ─────────────────────────────────────────────────────────────

class TypeHierarchy:
    """
    AION §3.1–§3.3: Type hierarchy H_T = (T ∪ {⊤}, ≺) as a DAG.

    Nodes  = type names (str)
    Edges  = child → parent  (τ → τ' means τ ≺ τ', i.e. τ is subtype of τ')
    Schema inheritance is enforced: σ(τ) ⊇ σ(τ') whenever τ ≺ τ'.

    Extended vs SILD:
      - Each node carries a TypeDef (schema included)
      - CompositionSchema comp(τ)
      - add_type() validates schema inheritance
      - effective_schema() merges inherited attrs bottom-up
    """

    ROOT = "⊤"   # Distinguished root: "clinical event"

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self._types: dict[str, TypeDef] = {}
        self._comp:  dict[str, set[str]] = {}   # comp(τ): allowed subprocess types

        # Bootstrap root
        root_schema = _root_schema()
        self._register(TypeDef(
            name=self.ROOT, parent=None,
            schema=root_schema,
            label="Clinical Event",
            description="Abstract root of all clinical event types (AION §3.1)",
        ))

        # Register built-in domain types
        self._init_default_types()

    # ── Internal registration ────────────────────────────────────────────────

    def _register(self, td: TypeDef) -> None:
        self._g.add_node(td.name)
        if td.parent is not None:
            self._g.add_edge(td.name, td.parent)
        self._types[td.name] = td

    def _init_default_types(self) -> None:
        """Register the standard AION clinical type set."""
        defaults: list[tuple[str, str, AttributeSchema, str]] = [
            # (name, parent, schema, label)
            ("Observation",  self.ROOT,       _obs_schema(),   "General Observation"),
            ("LabResult",    "Observation",   _lab_schema(),   "Laboratory Result"),
            ("VitalSign",    "Observation",   _obs_schema(),   "Vital Sign"),
            ("Score",        "Observation",   _score_schema(), "Clinical Score"),
            ("Imaging",      self.ROOT,       _img_schema(),   "Imaging Study"),
            ("Procedure",    self.ROOT,       _op_schema(),    "Surgical Procedure"),
            ("HLMPhase",     "Procedure",     _hlm_schema(),   "Heart-Lung Machine Phase"),
            ("Anaesthesia",  "Procedure",     _op_schema(),    "Anaesthesia Phase"),
            ("Diagnosis",    self.ROOT,       _dx_schema(),    "Diagnosis / Condition"),
            ("Medication",   self.ROOT,       _med_schema(),   "Medication Administration"),
            ("Encounter",    self.ROOT,       _root_schema(),  "Clinical Encounter / Stay"),
            ("Consultation", self.ROOT,       _root_schema(),  "Consultation"),
            ("Episode",      self.ROOT,       _root_schema(),  "Derived Episode"),
            # FHIR mirror types (for SILD compatibility)
            ("fhir:Observation",             "Observation",  _obs_schema(),  "FHIR Observation"),
            ("fhir:Procedure",               "Procedure",    _op_schema(),   "FHIR Procedure"),
            ("fhir:Condition",               "Diagnosis",    _dx_schema(),   "FHIR Condition"),
            ("fhir:MedicationAdministration","Medication",   _med_schema(),  "FHIR MedicationAdministration"),
            ("fhir:MedicationRequest",       "Medication",   _med_schema(),  "FHIR MedicationRequest"),
            ("fhir:Encounter",               "Encounter",    _root_schema(), "FHIR Encounter"),
            ("fhir:DiagnosticReport",        "LabResult",    _lab_schema(),  "FHIR DiagnosticReport"),
        ]
        for name, parent, schema, label in defaults:
            # Merge inherited schema from parent
            merged = self._merge_schema(schema, parent)
            self._register(TypeDef(name=name, parent=parent, schema=merged, label=label))

        # Default composition rules (AION §8.2)
        self._comp = {
            "Procedure":   {"HLMPhase", "Anaesthesia", "LabResult", "Observation"},
            "HLMPhase":    {"LabResult", "Observation"},
            "Encounter":   {"Procedure", "Diagnosis", "Medication", "Observation",
                            "LabResult", "Score", "Imaging", "Consultation"},
            "Consultation":{"Observation", "Diagnosis"},
        }

    def _merge_schema(
        self, own: AttributeSchema, parent_name: str
    ) -> AttributeSchema:
        """Merge own schema with inherited parent schema (σ(τ) ⊇ σ(τ'))."""
        if parent_name not in self._types:
            return own
        return own.union(self._types[parent_name].schema)

    # ── Public type management ───────────────────────────────────────────────

    def add_type(
        self,
        name:   str,
        parent: str,
        schema: AttributeSchema,
        label:  str = "",
        description: str = "",
        composition: Optional[set[str]] = None,
    ) -> TypeDef:
        """
        Add a new type τ to the hierarchy.
        Validates DAG property and schema inheritance.
        """
        if name in self._types:
            raise ValueError(f"Type '{name}' already registered")
        if parent not in self._types:
            raise ValueError(f"Parent type '{parent}' not found in hierarchy")

        # Validate schema inheritance
        parent_schema = self._types[parent].schema
        merged = schema.union(parent_schema)
        if not merged.is_subschema_of(parent_schema):
            raise ValueError(
                f"Schema of '{name}' does not subsume parent '{parent}' schema"
            )

        td = TypeDef(name=name, parent=parent, schema=merged,
                     label=label, description=description)
        self._register(td)

        # DAG check
        if not nx.is_directed_acyclic_graph(self._g):
            self._g.remove_node(name)
            del self._types[name]
            raise ValueError(f"Adding '{name}' → '{parent}' would create a cycle")

        if composition is not None:
            self._comp[name] = set(composition)

        return td

    def remove_type(self, name: str) -> None:
        """Remove a leaf type (no children allowed)."""
        if name == self.ROOT:
            raise ValueError("Cannot remove root type")
        children = [n for n in self._g.nodes if self._g.has_edge(n, name) and n != name]
        if children:
            raise ValueError(f"Cannot remove '{name}': has subtypes {children}")
        self._g.remove_node(name)
        del self._types[name]
        self._comp.pop(name, None)

    # ── Hierarchy queries ────────────────────────────────────────────────────

    def is_subtype(self, child: str, ancestor: str) -> bool:
        """True iff child ≺* ancestor (reflexive transitive)."""
        if child == ancestor:
            return True
        if child not in self._g or ancestor not in self._g:
            return False
        return nx.has_path(self._g, child, ancestor)

    def lca(self, a: str, b: str) -> Optional[str]:
        """Least common ancestor in the type DAG."""
        try:
            above_a = nx.descendants(self._g, a) | {a}
            above_b = nx.descendants(self._g, b) | {b}
            common  = above_a & above_b
            if not common:
                return None
            return max(common, key=lambda n: len(nx.descendants(self._g, n)))
        except nx.NodeNotFound:
            return None

    def ancestors(self, name: str) -> set[str]:
        """All ancestors of *name* (exclusive)."""
        if name not in self._g:
            return set()
        return nx.descendants(self._g, name)

    def subtypes(self, name: str) -> set[str]:
        """All strict subtypes of *name* (exclusive)."""
        return nx.ancestors(self._g, name)

    def direct_subtypes(self, name: str) -> list[str]:
        """Immediate children of *name* in the hierarchy."""
        return [n for n in self._g.nodes if self._g.has_edge(n, name)]

    def effective_schema(self, name: str) -> AttributeSchema:
        """σ(name) already merged with all parent schemas."""
        if name not in self._types:
            raise KeyError(f"Type '{name}' not found")
        return self._types[name].schema

    def typedef(self, name: str) -> TypeDef:
        if name not in self._types:
            raise KeyError(f"Type '{name}' not found")
        return self._types[name]

    # ── CompositionSchema comp(τ) ────────────────────────────────────────────

    def set_composition(self, parent_type: str, allowed: set[str]) -> None:
        """Define comp(parent_type) = allowed (subprocess types)."""
        for t in allowed:
            if t not in self._types:
                raise KeyError(f"Unknown type in composition: '{t}'")
        self._comp[parent_type] = set(allowed)

    def add_to_composition(self, parent_type: str, subtype: str) -> None:
        self._comp.setdefault(parent_type, set()).add(subtype)

    def allowed_subtypes(self, parent_type: str) -> set[str]:
        """Return comp(parent_type); empty set means no subprocess allowed."""
        return self._comp.get(parent_type, set())

    def composition_valid(self, parent_type: str, sub_type: str) -> bool:
        """Check type(e2) ∈ comp(type(e1))."""
        allowed = self._comp.get(parent_type, set())
        # Also accept any subtype of an allowed type
        return any(self.is_subtype(sub_type, a) for a in allowed)

    # ── Validation ───────────────────────────────────────────────────────────

    def validate_attrs(
        self, type_name: str, attrs: dict[str, Any]
    ) -> list[str]:
        """Validate attribute dict against the effective schema of *type_name*."""
        if type_name not in self._types:
            return [f"Unknown type: '{type_name}'"]
        return self._types[type_name].schema.validate_instance(attrs)

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def all_types(self) -> list[str]:
        return list(self._types.keys())

    @property
    def graph(self) -> nx.DiGraph:
        return self._g

    def __contains__(self, name: str) -> bool:
        return name in self._types

    def __repr__(self) -> str:
        n = len(self._types)
        return f"TypeHierarchy({n} types, root='{self.ROOT}')"


# ── Module-level singleton ────────────────────────────────────────────────────

_DEFAULT_HIERARCHY: Optional[TypeHierarchy] = None


def default_hierarchy() -> TypeHierarchy:
    """Return the module-level default TypeHierarchy (lazy singleton)."""
    global _DEFAULT_HIERARCHY
    if _DEFAULT_HIERARCHY is None:
        _DEFAULT_HIERARCHY = TypeHierarchy()
    return _DEFAULT_HIERARCHY


def reset_default_hierarchy() -> None:
    """Reset singleton — useful in tests."""
    global _DEFAULT_HIERARCHY
    _DEFAULT_HIERARCHY = None
